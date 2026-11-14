"""
Shared helpers for the backend test suite.
"""

import io


def register_user(client, *, email="test@example.com", full_name="Test User",
                  password="StudyHard2026"):
    """Register an account and return ``(user, token)``."""
    response = client.post(
        "/api/auth/register",
        json={"email": email, "full_name": full_name, "password": password},
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    payload = response.get_json()["data"]
    return payload["user"], payload["token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def text_upload(content: str, filename: str = "notes.txt"):
    """Build a ``multipart/form-data`` file tuple for the test client."""
    return {"file": (io.BytesIO(content.encode("utf-8")), filename)}


def make_pdf_bytes(text: str) -> bytes:
    """Create a minimal digital-text PDF in memory (no OCR needed)."""
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(fitz.Rect(50, 50, 545, 790), text, fontsize=11)
    data = document.tobytes()
    document.close()
    return data


def pdf_upload(text: str, filename: str = "notes.pdf"):
    return {"file": (io.BytesIO(make_pdf_bytes(text)), filename)}


def make_scanned_pdf_bytes(text: str = "Scanned line one.\nScanned line two.") -> bytes:
    """Create an image-only PDF (no text layer) to force the OCR path in tests."""
    import fitz
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (600, 200), "white")
    ImageDraw.Draw(image).text((20, 20), text, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    document = fitz.open()
    page = document.new_page(width=595, height=300)
    page.insert_image(fitz.Rect(10, 10, 585, 290), stream=buffer.getvalue())
    data = document.tobytes()
    document.close()
    return data


def scanned_pdf_upload(filename: str = "scan.pdf"):
    return {"file": (io.BytesIO(make_scanned_pdf_bytes()), filename)}


def upload(client, token, files, *, subject=""):
    return client.post(
        "/api/documents",
        data={**files, "subject": subject},
        headers=auth_headers(token),
        content_type="multipart/form-data",
    )
