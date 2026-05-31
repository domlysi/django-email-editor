from django.contrib.auth.models import User

from email_editor.preview import EmailPreview, register


@register
class WelcomeEmailPreview(EmailPreview):
    template_name = 'test'
    is_post_office = True
    # language = 'en'

    def get_template_context(self, *args, **kwargs):
        return {
            'user': User.objects.first(),
            'test': {
                'Test': 'test'
            }
        }


@register
class WelcomeEmailEnPreview(EmailPreview):
    template_name = 'test_project/welcome_mail.html'
    label = "Welcome Mail (legacy)"
    category = "Examples"

    def get_template_context(self, *args, **kwargs):
        return {
            'user': User.objects.first(),
            'test': {
                'Test': 'test'
            }
        }


@register
class OrderConfirmationPreview(EmailPreview):
    template_name = "test_project/order_confirmation.html"
    label = "Order Confirmation"
    category = "Examples"

    def get_template_context(self, *args, **kwargs):
        return {
            "user": User.objects.first(),
            "order": {
                "number": "ORD-20260530-0042",
                "date": "May 30, 2026",
                "items": [
                    {
                        "name": "Wireless Keyboard Pro",
                        "variant": "Black / US Layout",
                        "qty": 1,
                        "price": "$89.99",
                    },
                    {
                        "name": "USB-C Hub (7-in-1)",
                        "variant": None,
                        "qty": 2,
                        "price": "$34.99",
                    },
                    {
                        "name": "Desk Mat XL",
                        "variant": "Charcoal Grey",
                        "qty": 1,
                        "price": "$24.99",
                    },
                ],
                "subtotal": "$184.96",
                "shipping": "$4.99",
                "total": "$189.95",
                "shipping_name": "Jane Doe",
                "shipping_address": "123 Main Street, Apt 4B",
                "shipping_city": "Berlin",
                "shipping_zip": "10115",
                "shipping_country": "Germany",
                "tracking_url": "https://example.com/track/ORD-20260530-0042",
            },
        }


@register
class PasswordResetPreview(EmailPreview):
    template_name = "test_project/password_reset.html"
    label = "Password Reset"
    category = "Examples"

    def get_template_context(self, *args, **kwargs):
        return {
            "user": User.objects.first(),
            "reset": {
                "url": "https://example.com/reset/abc123xyz",
                "expires_in": "24 hours",
            },
        }


@register
class WelcomeOnboardingPreview(EmailPreview):
    template_name = "test_project/welcome_onboarding.html"
    label = "Welcome / Onboarding"
    category = "Examples"

    def get_template_context(self, *args, **kwargs):
        return {
            "user": User.objects.first(),
            "onboarding_url": "https://example.com/onboarding",
            "login_url": "https://example.com/login",
        }


@register
class NewsletterPreview(EmailPreview):
    template_name = "test_project/newsletter.html"
    label = "Monthly Newsletter"
    category = "Examples"

    def get_template_context(self, *args, **kwargs):
        return {
            "user": User.objects.first(),
            "newsletter": {
                "month": "May",
                "year": "2026",
                "lead": {
                    "title": "New Features That Will Change How You Work",
                    "excerpt": (
                        "This month we shipped a complete redesign of the dashboard, new keyboard shortcuts, "
                        "and a powerful batch processing mode. Here's everything you need to know to take "
                        "advantage of these improvements right away."
                    ),
                    "url": "https://example.com/blog/may-2026",
                },
                "articles": [],
            },
            "stats": {
                "users": "12,840",
                "requests": "4.2M",
                "uptime": "99.98%",
            },
        }
