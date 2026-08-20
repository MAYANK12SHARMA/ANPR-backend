import mimetypes
import os
import smtplib
from email.message import EmailMessage


class EmailSender:
    """
    Handles SMTP email sending.

    Responsibilities:
    - Validate SMTP configuration
    - Connect to SMTP server
    - Build HTML email
    - Attach files
    - Send email
    """

    def __init__(self):
        self.smtp_host = os.getenv("SMTP_HOST")
        self.smtp_port = int(os.getenv("SMTP_PORT", 587))
        self.smtp_username = os.getenv("SMTP_USERNAME")
        self.smtp_password = os.getenv("SMTP_PASSWORD")
        self.smtp_from = os.getenv("SMTP_FROM")

        if not all(
            [
                self.smtp_host,
                self.smtp_port,
                self.smtp_username,
                self.smtp_password,
                self.smtp_from,
            ]
        ):
            raise ValueError(
                "SMTP configuration is incomplete. " "Please check your .env file."
            )

    def send_email(
        self,
        recipients: list[str],
        subject: str,
        html_body: str,
        attachments: list[str] | None = None,
    ) -> bool:
        """
        Send an HTML email with optional attachments.

        Returns:
            True  -> Email sent successfully
            False -> Failed to send email
        """

        if not recipients:
            print("[EMAIL] No recipients supplied.")
            return False

        try:

            message = EmailMessage()

            message["Subject"] = subject
            message["From"] = self.smtp_from
            message["To"] = ", ".join(recipients)

            message.set_content("Your email client does not support HTML emails.")

            message.add_alternative(
                html_body,
                subtype="html",
            )

            attachment_count = 0

            if attachments:

                for file_path in attachments:

                    if not os.path.exists(file_path):
                        print(f"[EMAIL] Attachment not found: {file_path}")
                        continue

                    mime_type, _ = mimetypes.guess_type(file_path)

                    if mime_type:
                        maintype, subtype = mime_type.split("/", 1)
                    else:
                        maintype = "application"
                        subtype = "octet-stream"

                    with open(file_path, "rb") as file:

                        message.add_attachment(
                            file.read(),
                            maintype=maintype,
                            subtype=subtype,
                            filename=os.path.basename(file_path),
                        )

                    attachment_count += 1

            print(f"[EMAIL] Sending email to " f"{', '.join(recipients)}")

            print(f"[EMAIL] Attachments: {attachment_count}")

            with smtplib.SMTP(
                self.smtp_host,
                self.smtp_port,
                timeout=30,
            ) as smtp:

                smtp.ehlo()

                smtp.starttls()

                smtp.ehlo()

                smtp.login(
                    self.smtp_username,
                    self.smtp_password,
                )

                smtp.send_message(message)

            print(f"[EMAIL] Successfully sent to " f"{', '.join(recipients)}")

            return True

        except Exception as e:

            print(f"[EMAIL ERROR] Failed sending email " f"to {', '.join(recipients)}")

            print(f"[EMAIL ERROR] {type(e).__name__}: {e}")

            return False
