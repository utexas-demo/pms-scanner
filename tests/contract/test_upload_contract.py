"""
Contract test for POST /api/scanned-images/upload — T015.

Skipped when BACKEND_BASE_URL is not set in the environment.
Requires a live backend reachable at BACKEND_BASE_URL with a valid API_TOKEN.
"""
import io
import os

import pytest
import requests
from PIL import Image


@pytest.mark.skipif(
    not os.environ.get("BACKEND_BASE_URL"),
    reason="BACKEND_BASE_URL not set — skipping live contract test",
)
def test_upload_endpoint_contract():
    """
    POST /api/scanned-images/upload returns the expected JSON shape.

    Response must contain:
        batch_id   str
        images     list
        rejected   list
    """
    backend_url = os.environ["BACKEND_BASE_URL"]
    api_token = os.environ.get("API_TOKEN", "")

    # Build a minimal JPEG in memory
    img = Image.new("RGB", (50, 50), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)

    response = requests.post(
        f"{backend_url}/api/scanned-images/upload",
        headers={"Authorization": f"Bearer {api_token}"},
        files=[("files", ("contract_test_p001.jpg", buf.read(), "image/jpeg"))],
        timeout=30,
    )

    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )

    body = response.json()
    assert "batch_id" in body, f"Missing 'batch_id' in response: {body}"
    assert "images" in body, f"Missing 'images' in response: {body}"
    assert "rejected" in body, f"Missing 'rejected' in response: {body}"
    assert isinstance(body["images"], list)
    assert isinstance(body["rejected"], list)
