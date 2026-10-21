
import base64
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from requests.auth import HTTPBasicAuth
from django.conf import settings


MPESA_BASE_URL = "https://sandbox.safaricom.co.ke"
REQUEST_TIMEOUT = 30


def _raise_mpesa_error(operation, response):
    """
    Raise a useful error without exposing credentials or tokens.
    """
    body = response.text[:500].strip()

    if body:
        details = repr(body)
    else:
        details = "empty response body"

    raise ValueError(
        f"M-Pesa {operation} failed. "
        f"HTTP status: {response.status_code}. "
        f"Response: {details}"
    )


def _get_json_response(response, operation):
    """
    Validate an HTTP response and safely parse its JSON body.
    """
    if not response.ok:
        _raise_mpesa_error(operation, response)

    try:
        data = response.json()
    except (requests.exceptions.JSONDecodeError, ValueError) as exc:
        raise ValueError(
            f"M-Pesa {operation} returned invalid JSON."
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"M-Pesa {operation} returned an unexpected response format."
        )

    return data


def get_mpesa_access_token():
    """
    Obtain an OAuth access token from Safaricom Daraja.
    """
    consumer_key = settings.MPESA_CONSUMER_KEY
    consumer_secret = settings.MPESA_CONSUMER_SECRET

    if not consumer_key or not consumer_secret:
        raise ValueError(
            "M-Pesa consumer credentials are missing. "
            "Check your environment settings."
        )

    url = f"{MPESA_BASE_URL}/oauth/v1/generate"

    try:
        response = requests.get(
            url,
            params={"grant_type": "client_credentials"},
            auth=HTTPBasicAuth(
                consumer_key,
                consumer_secret,
            ),
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ValueError(
            "Could not connect to the M-Pesa OAuth service. "
            "Check your internet connection and try again."
        ) from exc

    data = _get_json_response(response, "OAuth authentication")

    access_token = data.get("access_token")

    if not isinstance(access_token, str) or not access_token:
        raise ValueError(
            "Safaricom did not return an access token."
        )

    return access_token


def get_mpesa_timestamp():
    """
    Generate a timestamp in the Africa/Nairobi time zone.
    """
    return datetime.now(
        ZoneInfo("Africa/Nairobi")
    ).strftime("%Y%m%d%H%M%S")


def get_mpesa_password(shortcode, passkey, timestamp):
    """
    Generate the Base64-encoded Daraja password.
    """
    raw_password = f"{shortcode}{passkey}{timestamp}"

    return base64.b64encode(
        raw_password.encode("utf-8")
    ).decode("utf-8")


def _get_mpesa_payment_settings():
    """
    Read and validate the shortcode and passkey.
    """
    shortcode = settings.MPESA_SHORTCODE
    passkey = settings.MPESA_PASSKEY

    if not shortcode or not passkey:
        raise ValueError(
            "M-Pesa shortcode or passkey is missing. "
            "Check your environment settings."
        )

    return shortcode, passkey


def _post_mpesa_json(endpoint, payload, operation):
    """
    Send an authenticated request to a Daraja endpoint.
    """
    access_token = get_mpesa_access_token()

    try:
        response = requests.post(
            f"{MPESA_BASE_URL}{endpoint}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ValueError(
            f"Could not connect to the M-Pesa {operation} service. "
            "The final payment outcome may be unknown; "
            "check the existing transaction before retrying."
        ) from exc

    return _get_json_response(response, operation)


def initiate_stk_push(
    phone_number,
    amount,
    callback_url,
    account_reference="CHAMALINK",
    description="Chama contribution",
):
    """
    Request an STK Push.

    An accepted request is not proof that payment succeeded.
    The callback or a verified transaction-status result must
    establish the final outcome.
    """
    if (
        not isinstance(amount, int)
        or isinstance(amount, bool)
        or amount < 1
    ):
        raise ValueError(
            "Amount must be a positive whole number."
        )

    if (
        not isinstance(phone_number, str)
        or not phone_number.startswith("254")
        or len(phone_number) != 12
        or not phone_number.isdigit()
    ):
        raise ValueError(
            "Enter a valid Kenyan phone number starting with 254."
        )

    if not callback_url or not callback_url.startswith("https://"):
        raise ValueError(
            "A valid HTTPS M-Pesa callback URL is required."
        )

    shortcode, passkey = _get_mpesa_payment_settings()

    timestamp = get_mpesa_timestamp()
    password = get_mpesa_password(
        shortcode,
        passkey,
        timestamp,
    )

    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone_number,
        "PartyB": shortcode,
        "PhoneNumber": phone_number,
        "CallBackURL": callback_url,
        "AccountReference": account_reference,
        "TransactionDesc": description,
    }

    return _post_mpesa_json(
        "/mpesa/stkpush/v1/processrequest",
        payload,
        "STK Push",
    )


def query_stk_push(checkout_request_id):
    """
    Query Safaricom for an existing STK Push request.

    This function does not initiate a new payment. A successful
    HTTP response still needs interpretation of ResultCode and
    other fields returned by Safaricom.
    """
    if (
        not isinstance(checkout_request_id, str)
        or not checkout_request_id.strip()
    ):
        raise ValueError(
            "CheckoutRequestID is required to query a payment."
        )

    shortcode, passkey = _get_mpesa_payment_settings()

    timestamp = get_mpesa_timestamp()
    password = get_mpesa_password(
        shortcode,
        passkey,
        timestamp,
    )

    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_request_id.strip(),
    }

    return _post_mpesa_json(
        "/mpesa/stkpushquery/v1/query",
        payload,
        "STK Push Query",
    )
