from PIL import Image, ImageOps


class AutoOrientProcessor:
    """Normalize image orientation based on EXIF metadata when present."""

    def process(self, image: Image.Image) -> Image.Image:
        return ImageOps.exif_transpose(image)
