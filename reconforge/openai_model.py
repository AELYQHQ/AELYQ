"""Optional OpenAI Responses API adapter.

The adapter is deliberately bounded:

- fixed OpenAI Responses endpoint
- no redirects
- no inherited proxy configuration
- no automatic retries
- no provider error-body leakage
- bounded request and response sizes
- strict response validation
- no stored provider conversation state
- bounded classification of known provider error codes
"""

import re

import httpx

from .investigation import InvestigationError, canonical_json
from .investigator import (
    MAX_INPUT_BYTES,
    ModelReply,
    SYSTEM_PROMPT,
    parse_object,
)


RESPONSES_URL = "https://api.openai.com/v1/responses"

MAX_OUTPUT_TOKENS = 4096
MAX_RESPONSE_BYTES = 262_144
MAX_ERROR_BODY_BYTES = 16_384


GENERIC_429_MESSAGE = (
    "HTTP 429: Check OpenAI quota or rate limits; "
    "no automatic retry was made."
)


KNOWN_PROVIDER_MESSAGES = {
    # Authentication
    (401, "invalid_api_key"): (
        "The provider rejected the API key; no retry was made."
    ),

    # Authorization / permissions
    (403, "permission_denied"): (
        "Check for insufficient project or model permissions; "
        "no retry was made."
    ),

    # Billing / quota / rate limiting
    (429, "insufficient_quota"): (
        "Check for insufficient quota or project spend capacity; "
        "no automatic retry was made."
    ),
    (429, "billing_hard_limit_reached"): (
        "Check the billing or spend limit; "
        "no automatic retry was made."
    ),
    (429, "rate_limit_exceeded"): (
        "Check the request or usage rate limit; "
        "no automatic retry was made."
    ),
    (429, "slow_down"): (
        "Check the rate limit; "
        "no automatic retry was made."
    ),
    (429, "organization_spend_limit_exceeded"): (
        "Check the organization spend limit; "
        "no automatic retry was made."
    ),
    (429, "project_spend_limit_exceeded"): (
        "Check the project spend limit; "
        "no automatic retry was made."
    ),
    (429, "usage_limit_exceeded"): (
        "Check the API usage limit; "
        "no automatic retry was made."
    ),
}


def classify_provider_error(
    status_code: int,
    body: bytes,
) -> str:
    """Return a fixed, sanitized message for a provider error.

    Only explicitly allow-listed provider error codes affect the
    message. Provider-controlled error messages are never returned.
    """

    provider_code = None
    provider_type = None

    try:
        decoded = body.decode("utf-8")
        payload = parse_object(decoded)

        error = payload.get("error")

        if isinstance(error, dict):
            candidate = error.get("code")
            if isinstance(candidate, str):
                provider_code = candidate

            candidate_type = error.get("type")
            if isinstance(candidate_type, str):
                provider_type = candidate_type

    except (
        UnicodeDecodeError,
        InvestigationError,
        ValueError,
        TypeError,
    ):
        provider_code = None
        provider_type = None

    known_message = KNOWN_PROVIDER_MESSAGES.get(
        (status_code, provider_code)
    )

    if known_message is not None:
        return known_message

    # OpenAI can communicate insufficient quota through the
    # error type even when no explicit error code is supplied.
    if (
        status_code == 429
        and provider_type == "insufficient_quota"
    ):
        return (
            "Check for insufficient quota or project spend capacity; "
            "no automatic retry was made."
        )

    if status_code == 401:
        return "Check your API key."

    if status_code == 403:
        return "Check project and model permissions."

    if status_code == 429:
        return GENERIC_429_MESSAGE

    return (
        "Check the selected model and API request compatibility."
    )


class OpenAIResponsesModel:
    """Bounded OpenAI Responses API model adapter."""

    mode = "openai_live"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if (
            not isinstance(api_key, str)
            or not api_key.strip()
            or any(character.isspace() for character in api_key)
        ):
            raise InvestigationError(
                "Supply a nonempty OpenAI API key without whitespace."
            )

        if (
            not isinstance(model, str)
            or not re.fullmatch(
                r"[a-zA-Z0-9_.:-]{1,128}",
                model,
            )
        ):
            raise InvestigationError(
                "Supply an explicit API model ID supporting "
                "Responses function calling."
            )

        self._api_key = api_key
        self.requested_model = model
        self._transport = transport

    async def complete(
        self,
        history: list[dict],
        tools: list[dict],
    ) -> ModelReply:
        """Execute exactly one bounded Responses API request."""

        payload = {
            "model": self.requested_model,
            "instructions": SYSTEM_PROMPT,
            "input": history,
            "tools": tools,
            "tool_choice": "required",
            "parallel_tool_calls": False,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "store": False,
            "include": [
                "reasoning.encrypted_content",
            ],
        }

        body = canonical_json(payload).encode("utf-8")

        if len(body) > MAX_INPUT_BYTES:
            raise InvestigationError(
                "The provider request exceeds the input byte budget."
            )

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(
                    30.0,
                    connect=10.0,
                ),
                transport=self._transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:

                async with client.stream(
                    "POST",
                    RESPONSES_URL,
                    content=body,
                    headers={
                        "Authorization": (
                            "Bearer " + self._api_key
                        ),
                        "Content-Type": "application/json",
                    },
                ) as response:

                    if response.status_code != 200:
                        error_body = bytearray()

                        async for chunk in response.aiter_bytes():
                            error_body.extend(chunk)

                            if (
                                len(error_body)
                                >= MAX_ERROR_BODY_BYTES
                            ):
                                break

                        guidance = classify_provider_error(
                            response.status_code,
                            bytes(
                                error_body[
                                    :MAX_ERROR_BODY_BYTES
                                ]
                            ),
                        )

                        raise InvestigationError(
                            f"OpenAI returned HTTP "
                            f"{response.status_code}. "
                            f"{guidance}"
                        )

                    response_body = bytearray()

                    async for chunk in response.aiter_bytes():
                        response_body.extend(chunk)

                        if (
                            len(response_body)
                            > MAX_RESPONSE_BYTES
                        ):
                            raise InvestigationError(
                                "The provider response exceeds "
                                "the byte limit."
                            )

        except httpx.HTTPError as exc:
            raise InvestigationError(
                "The OpenAI request failed or timed out; "
                "no automatic retry was made."
            ) from exc

        try:
            decoded_response = response_body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvestigationError(
                "The provider returned invalid UTF-8."
            ) from exc

        try:
            result = parse_object(decoded_response)
        except InvestigationError:
            raise
        except (
            ValueError,
            TypeError,
        ) as exc:
            raise InvestigationError(
                "The provider returned malformed JSON."
            ) from exc

        if result.get("status") != "completed":
            raise InvestigationError(
                "The provider response was incomplete "
                "or failed; no plan was accepted."
            )

        output = result.get("output")
        usage = result.get("usage")
        returned_model = result.get("model")

        if not isinstance(output, list):
            raise InvestigationError(
                "The provider response lacks valid output."
            )

        if not isinstance(usage, dict):
            raise InvestigationError(
                "The provider response lacks valid usage metadata."
            )

        if not isinstance(returned_model, str):
            raise InvestigationError(
                "The provider response lacks model identity."
            )

        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")

        if (
            type(input_tokens) is not int
            or input_tokens < 0
        ):
            raise InvestigationError(
                "The provider returned invalid input token usage."
            )

        if (
            type(output_tokens) is not int
            or output_tokens < 0
        ):
            raise InvestigationError(
                "The provider returned invalid output token usage."
            )

        return ModelReply(
            output=output,
            returned_model=returned_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )