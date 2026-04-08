from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image  # type: ignore[import-not-found]

from borrowd.models import TrustLevel
from borrowd_items.models import Item, ItemPhoto
from borrowd_users.models import BorrowdUser


def build_uploaded_image(
    *,
    width: int,
    height: int,
    exif_orientation: int | None = None,
) -> SimpleUploadedFile:
    image = Image.new("RGB", (width, height), color="red")
    image_bytes = BytesIO()

    if exif_orientation is None:
        image.save(image_bytes, format="JPEG")
    else:
        exif = Image.Exif()
        exif[274] = exif_orientation
        image.save(image_bytes, format="JPEG", exif=exif)

    image_bytes.seek(0)
    return SimpleUploadedFile(
        name="photo.jpg",
        content=image_bytes.read(),
        content_type="image/jpeg",
    )


class ItemPhotoOrientationTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.owner = BorrowdUser.objects.create(
            username="orientation-owner",
            email="orientation-owner@example.com",
        )
        cls.item = Item.objects.create(
            name="Orientation Test Item",
            description="Used for photo orientation tests",
            owner=cls.owner,
            trust_level_required=TrustLevel.STANDARD,
        )

    def test_phone_exif_orientation_is_applied_to_processed_image(self) -> None:
        uploaded_image = build_uploaded_image(width=300, height=500, exif_orientation=6)

        item_photo = ItemPhoto.objects.create(item=self.item, image=uploaded_image)

        with Image.open(item_photo.image) as processed_image:
            self.assertEqual(processed_image.size, (1600, 960))

        self.assertEqual(item_photo.thumbnail.width, 200)
        self.assertEqual(item_photo.thumbnail.height, 200)

    def test_upload_without_orientation_metadata_keeps_pixel_orientation(self) -> None:
        uploaded_image = build_uploaded_image(width=300, height=500)

        item_photo = ItemPhoto.objects.create(item=self.item, image=uploaded_image)

        with Image.open(item_photo.image) as processed_image:
            self.assertEqual(processed_image.size, (960, 1600))
