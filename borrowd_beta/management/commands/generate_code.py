from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandParser

from borrowd_beta.models import BetaCode


class Command(BaseCommand):
    help = "Generates a 7-character alphanumeric code (uppercase letters and digits) and stores it with a name/email"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("name", type=str, help="Name of the user")
        parser.add_argument(
            "--email", type=str, help="Email of the user", required=False
        )

    def handle(self, *args: Any, **options: Any) -> None:
        name = options["name"]
        email = options["email"]

        try:
            code = BetaCode.generate_code()
            BetaCode.objects.create(name=name, email=email, code=code)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully generated code: {code} for {name} ({email})"
                )
            )
        except ValidationError as e:
            self.stderr.write(self.style.ERROR(f"Error: {e.message_dict}"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error: {str(e)}"))
