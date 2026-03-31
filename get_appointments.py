#!/usr/bin/env python3
"""
Fetch appointments from Athena Health patient portal.
Automatically authenticates to get bearer token from login credentials.
"""

import requests
import json
import sys
import os
import subprocess
from argparse import ArgumentParser
from typing import Optional, Tuple
from urllib.parse import urljoin, parse_qs, urlparse

BASE_URL = "https://ptl-api-prod2603261936.ch.px.athenahealth.com/px/ptl"


def get_credentials_from_1password(item_id: Optional[str] = None, vault: Optional[str] = None) -> Tuple[str, str]:
    """
    Retrieve Athena Health credentials from 1password CLI.

    Args:
        item_id: 1password item ID (if not specified, searches for "athena" item)
        vault: Optional vault name (if not specified, searches all vaults)

    Returns:
        Tuple of (username, password)
    """
    try:
        athena_item = item_id

        # If no item ID provided, search for Athena Health credentials
        if not athena_item:
            cmd = ["op", "item", "list"]
            if vault:
                cmd += ["--vault", vault]
            search_result = subprocess.run(cmd, capture_output=True, text=True, check=False)

            if search_result.returncode != 0:
                return None, None

            # Try to find an item with "athena" in the name
            items = json.loads(search_result.stdout)
            for item in items:
                if "athena" in item.get("title", "").lower():
                    athena_item = item["id"]
                    break

            if not athena_item:
                return None, None

        # Get the item details
        get_cmd = ["op", "item", "get", athena_item]
        get_result = subprocess.run(get_cmd, capture_output=True, text=True, check=True)
        item_data = json.loads(get_result.stdout)

        username = None
        password = None
        for field in item_data.get("fields", []):
            if field.get("type") == "STRING":
                label = field.get("label", "").lower()
                if "username" in label or "email" in label:
                    username = field.get("value")
                elif "password" in label:
                    password = field.get("value")

        return username, password
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error retrieving from 1password: {e}", file=sys.stderr)
        return None, None


def get_credentials(args) -> Tuple[str, str, str]:
    """
    Get credentials from various sources in order of preference:
    1. Command-line arguments
    2. Environment variables
    3. 1password CLI
    4. stdin prompts

    Returns:
        Tuple of (username, password, patient_id)
    """
    username = args.username or os.getenv("ATHENA_USERNAME")
    password = args.password or os.getenv("ATHENA_PASSWORD")
    patient_id = args.patient_id or os.getenv("ATHENA_PATIENT_ID")

    # Try 1password if credentials missing
    if not username or not password:
        print("Attempting to retrieve credentials from 1password...", file=sys.stderr)
        op_user, op_pass = get_credentials_from_1password(args.op_id, args.vault)
        if op_user and op_pass:
            username = op_user
            password = op_pass
            print("✓ Retrieved credentials from 1password", file=sys.stderr)

    # Fall back to stdin prompts
    if not username:
        username = input("Athena Health username/email: ")
    if not password:
        import getpass
        password = getpass.getpass("Athena Health password: ")
    if not patient_id:
        patient_id = input("Patient ID (leave blank to use from profile): ").strip() or None

    return username, password, patient_id


def authenticate(username: str, password: str) -> Optional[Tuple[str, str]]:
    """
    Authenticate with Athena Health and get bearer token and patient ID.

    Returns:
        Tuple of (bearer_token, patient_id) or None if authentication fails
    """
    # Start OAuth flow with Athena Health portal
    portal_url = "https://21279-2.portal.athenahealth.com/"

    session = requests.Session()

    try:
        # Get the portal page to extract OAuth parameters
        print("Initiating authentication...", file=sys.stderr)
        portal_response = session.get(portal_url)

        # The actual authentication happens through Okta
        # This is a simplified approach - you may need to adjust based on actual flow

        # Try direct API login (if available)
        login_url = "https://myidentity.platform.athenahealth.com/oauth2/auset0ja9xZ2Hniep296/v1/token"
        login_data = {
            "username": username,
            "password": password,
            "grant_type": "password",
            "client_id": "0oaku1tngsTH20pA1296",
        }

        login_response = session.post(login_url, data=login_data, allow_redirects=True)

        if login_response.status_code == 200:
            token_data = login_response.json()
            bearer_token = token_data.get("access_token")

            if bearer_token:
                print("✓ Authentication successful", file=sys.stderr)
                # Patient ID would need to be extracted from profile or passed separately
                return bearer_token, None

        print(f"Authentication failed: {login_response.status_code}", file=sys.stderr)
        print("Note: Full OAuth flow may require browser-based authentication.", file=sys.stderr)
        return None, None

    except requests.exceptions.RequestException as e:
        print(f"Authentication error: {e}", file=sys.stderr)
        return None, None


def get_appointments(bearer_token: str, patient_id: str, appointment_type: str = "past", use_fhir: bool = False) -> dict:
    """
    Fetch appointments from Athena Health API

    Args:
        bearer_token: JWT bearer token from Athena Health
        patient_id: Patient ID
        appointment_type: "past" or "upcoming" (default: "past")
        use_fhir: Use FHIR format endpoint (more detailed, default: False)

    Returns:
        JSON response from the API
    """
    if use_fhir:
        url = f"{BASE_URL}/appointment.fhir-2023-04?patientId={patient_id}"
    else:
        url = f"{BASE_URL}/appointments/{appointment_type}?patientId={patient_id}"

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:149.0) Gecko/20100101 Firefox/149.0",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Authorization": f"Bearer {bearer_token}",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "Priority": "u=4",
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching appointments: {e}", file=sys.stderr)
        sys.exit(1)


def print_fhir_appointments(data: dict) -> None:
    """Pretty-print FHIR-format appointment data."""
    if not isinstance(data, dict) or "entry" not in data:
        print(json.dumps(data, indent=2))
        return

    entries = data["entry"]
    if not entries:
        print("No appointments found")
        return

    print(f"Found {len(entries)} appointment(s):\n")
    for entry in entries:
        resource = entry.get("resource", {})
        participants = resource.get("participant", [])
        provider = participants[0].get("actor", {}).get("display", "N/A") if participants else "N/A"

        print(f"Date/Time: {resource.get('start', 'N/A')}")
        print(f"Provider: {provider}")
        print(f"Status: {resource.get('status', 'N/A')}")
        print(f"Description: {resource.get('description', 'N/A')}")
        print("-" * 40)


def print_appointments(data: dict, appointment_type: str) -> None:
    """Pretty-print standard appointment data."""
    if not isinstance(data, dict) or "appointments" not in data:
        print(json.dumps(data, indent=2))
        return

    appointments = data["appointments"]
    if not appointments:
        print(f"No {appointment_type} appointments found")
        return

    print(f"Found {len(appointments)} {appointment_type} appointment(s):\n")
    for apt in appointments:
        print(f"Date: {apt.get('appointmentDate', 'N/A')}")
        print(f"Time: {apt.get('appointmentTime', 'N/A')}")
        print(f"Provider: {apt.get('providerName', 'N/A')}")
        print(f"Type: {apt.get('appointmentType', 'N/A')}")
        print(f"Status: {apt.get('appointmentStatus', 'N/A')}")
        print("-" * 40)


def main():
    parser = ArgumentParser(description="Fetch Athena Health appointments")
    parser.add_argument("--username", help="Username/email (or set ATHENA_USERNAME env var)")
    parser.add_argument("--password", help="Password (or set ATHENA_PASSWORD env var)")
    parser.add_argument("--patient-id", help="Patient ID (or set ATHENA_PATIENT_ID env var)")
    parser.add_argument("--token", help="Bearer token (skips authentication)")
    parser.add_argument("--op-id", help="1password item ID (e.g., 3evexyitmks2gj2iarwmrmj6ly)")
    parser.add_argument("--vault", help="1password vault name")
    parser.add_argument("--type", default="upcoming", choices=["past", "upcoming"],
                        help="Appointment type (default: upcoming)")
    parser.add_argument("--fhir", action="store_true", help="Use FHIR format endpoint (more detailed)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")

    args = parser.parse_args()

    # Get bearer token
    if args.token:
        bearer_token = args.token
        patient_id = args.patient_id or "21179"
        print("Using provided bearer token", file=sys.stderr)
    else:
        username, password, patient_id = get_credentials(args)

        # Attempt authentication
        auth_result = authenticate(username, password)
        if not auth_result or not auth_result[0]:
            print("\n⚠️  Full OAuth flow may require browser-based login.", file=sys.stderr)
            print("You can manually get your bearer token by:", file=sys.stderr)
            print("  1. Logging in at: https://21279-2.portal.athenahealth.com/", file=sys.stderr)
            print("  2. Opening browser DevTools (F12), Network tab", file=sys.stderr)
            print("  3. Looking for API requests with 'Authorization: Bearer ...' header", file=sys.stderr)
            print("\nThen run: python3 get_appointments.py --token YOUR_TOKEN --patient-id YOUR_ID", file=sys.stderr)
            sys.exit(1)

        bearer_token, _ = auth_result
        if not patient_id:
            patient_id = "21179"

    # Fetch appointments
    data = get_appointments(bearer_token, patient_id, args.type, use_fhir=args.fhir)

    if args.json:
        print(json.dumps(data, indent=2))
    elif args.fhir:
        print_fhir_appointments(data)
    else:
        print_appointments(data, args.type)


if __name__ == "__main__":
    main()
