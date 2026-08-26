import base64

from app.storage import storage_description, store_media_bytes


# 1x1 transparent PNG
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def main() -> None:
    print("Storage:", storage_description())
    url = store_media_bytes(
        data=PNG,
        filename="storage_test.png",
        content_type="image/png",
        folder="artigianai/storage-test",
    )
    print("Upload OK:", url)


if __name__ == "__main__":
    main()
