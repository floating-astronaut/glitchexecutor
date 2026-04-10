"""
GlitchExecutor Email Service
Sends transactional emails via Resend (https://resend.com).

Emails sent:
  - Welcome / subscription confirmed
  - Payment failed
  - Subscription cancelled
  - Trial ending reminder
"""
import logging
import os
from datetime import datetime

import resend

logger = logging.getLogger("EmailService")

# ─── Config (set in .env) ────────────────────────────────────────────────────
EMAIL_FROM  = os.environ.get("EMAIL_FROM", "support@glitchexecutor.com")
SITE_URL    = os.environ.get("SITE_URL", "https://glitchexecutor.com")

# ─── Resend client ──────────────────────────────────────────────────────────
resend.api_key = os.environ.get("RESEND_API_KEY", "")


# ─── Core send ───────────────────────────────────────────────────────────────

def send_email(to_address: str, subject: str, html_body: str, text_body: str = "") -> bool:
    """Send an email via Resend. Returns True on success."""
    if not to_address:
        logger.warning("send_email called with empty to_address — skipped")
        return False
    if not resend.api_key:
        logger.error("RESEND_API_KEY not set — cannot send email")
        return False
    try:
        resend.Emails.send({
            "from": f"GlitchExecutor <{EMAIL_FROM}>",
            "to": [to_address],
            "subject": subject,
            "html": html_body,
            "text": text_body or _html_to_text(subject),
        })
        logger.info(f"Email sent → {to_address} | {subject}")
        return True
    except Exception as e:
        logger.error(f"Email error: {e}")
        return False


def _html_to_text(subject: str) -> str:
    return f"{subject}\n\nVisit {SITE_URL} for details."


# ─── Shared template wrapper ─────────────────────────────────────────────────

def _wrap(title: str, body: str, cta_url: str = "", cta_label: str = "",
          footer_note: str = "") -> str:
    """Wrap content in the GlitchExecutor branded email shell."""
    cta_block = ""
    if cta_url and cta_label:
        cta_block = f"""
        <div style="text-align:center;margin:32px 0;">
          <a href="{cta_url}"
             style="background:#00ff88;color:#000;text-decoration:none;
                    font-weight:700;font-size:15px;padding:14px 32px;
                    border-radius:6px;display:inline-block;letter-spacing:.5px;">
            {cta_label}
          </a>
        </div>"""

    default_footer = (
        f'You\'re receiving this because you signed up at '
        f'<a href="{SITE_URL}" style="color:#00ff88;text-decoration:none;">glitchexecutor.com</a>.'
        f'&nbsp;|&nbsp;'
        f'<a href="{SITE_URL}/unsubscribe" style="color:#555;text-decoration:none;">Unsubscribe</a>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:'Helvetica Neue',Arial,sans-serif;">
  <!-- outer wrapper -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#0a0a0a;padding:40px 16px;">
    <tr><td align="center">
      <!-- card -->
      <table width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;background:#111318;border-radius:12px;
                    border:1px solid #1e2330;overflow:hidden;">

        <!-- header bar -->
        <tr>
          <td style="background:linear-gradient(135deg,#0a0a0a 0%,#0d1117 100%);
                     border-bottom:2px solid #00ff88;padding:28px 40px;">
            <div style="display:flex;align-items:center;gap:12px;">
              <span style="font-size:22px;font-weight:800;color:#fff;letter-spacing:-0.5px;">
                ⚡ GlitchExecutor
              </span>
            </div>
            <p style="margin:6px 0 0;color:#888;font-size:13px;letter-spacing:.5px;">
              AI-Powered Crypto Trading
            </p>
          </td>
        </tr>

        <!-- body -->
        <tr>
          <td style="padding:36px 40px;">
            <h1 style="margin:0 0 20px;color:#fff;font-size:22px;font-weight:700;line-height:1.3;">
              {title}
            </h1>
            {body}
            {cta_block}
          </td>
        </tr>

        <!-- footer -->
        <tr>
          <td style="padding:20px 40px 28px;border-top:1px solid #1e2330;">
            <p style="margin:0;color:#555;font-size:12px;line-height:1.6;">
              {footer_note or default_footer}
            </p>
            <p style="margin:8px 0 0;color:#333;font-size:11px;">
              &copy; {datetime.utcnow().year} GlitchExecutor. All rights reserved.
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _p(text: str) -> str:
    return f'<p style="margin:0 0 16px;color:#ccc;font-size:15px;line-height:1.7;">{text}</p>'


def _ul(items: list) -> str:
    lis = "".join(
        f'<li style="margin:0 0 8px;color:#ccc;font-size:15px;">{item}</li>'
        for item in items
    )
    return f'<ul style="margin:0 0 20px;padding-left:20px;">{lis}</ul>'


def _badge(label: str, color: str = "#00ff88") -> str:
    return (f'<span style="background:{color}22;color:{color};border:1px solid {color}55;'
            f'font-size:12px;font-weight:700;padding:3px 10px;border-radius:20px;'
            f'letter-spacing:.5px;">{label}</span>')


def _info_box(text: str, color: str = "#00ff88") -> str:
    return (f'<div style="background:{color}11;border-left:3px solid {color};'
            f'border-radius:4px;padding:14px 18px;margin:0 0 20px;">'
            f'<p style="margin:0;color:#ccc;font-size:14px;line-height:1.6;">{text}</p>'
            f'</div>')


# ─── Email #1: Welcome / Subscription Confirmed ──────────────────────────────

TIER_LIMITS = {
    "starter": {"analyses": "30 analyses/day", "assets": "BTC, ETH, SOL & XRP", "execution": "Portfolio view only"},
    "pro":      {"analyses": "100 analyses/day", "assets": "All supported assets", "execution": "Testnet auto-execution"},
    "elite":    {"analyses": "Unlimited analyses", "assets": "All supported assets", "execution": "MT5 live bot deployment"},
}

TIER_EMOJI = {"starter": "⭐", "pro": "🤖", "elite": "🏢"}


def send_welcome_email(to_email: str, tier: str, telegram_username: str = "") -> bool:
    tier = tier.lower()
    emoji = TIER_EMOJI.get(tier, "🔮")
    tier_label = tier.title()
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["starter"])
    tg_note = (f" Your Telegram handle <b>@{telegram_username.lstrip('@')}</b> is linked — "
               f"open the bot and type any crypto symbol to start."
               if telegram_username else
               " Open the bot and send <code>/start</code> to begin.")

    body = "".join([
        _p(f"Your <b>{emoji} {tier_label}</b> plan is now active. Here's what you have:"),
        _ul([
            f"<b>{limits['analyses']}</b> from our 9-model AI ensemble",
            f"<b>Assets covered:</b> {limits['assets']}",
            f"<b>Execution:</b> {limits['execution']}",
            "Priority support via Telegram",
        ]),
        _info_box(
            f"<b>Next step:</b>{tg_note}",
            "#00ff88"
        ),
        _p(
            'Need help? Reply to this email or message us on '
            f'<a href="{SITE_URL}" style="color:#00ff88;">Telegram</a>.'
        ),
    ])

    html = _wrap(
        title=f"{emoji} Welcome to GlitchExecutor {tier_label}!",
        body=body,
        cta_url="https://t.me/GlitchExecutorBot",
        cta_label="Open Telegram Bot →",
    )

    text = (
        f"Welcome to GlitchExecutor {tier_label}!\n\n"
        f"Your {tier_label} plan is active.\n"
        f"- {limits['analyses']}\n"
        f"- Assets: {limits['assets']}\n"
        f"- Execution: {limits['execution']}\n\n"
        f"Open the bot: https://t.me/GlitchExecutorBot\n"
        f"Manage account: {SITE_URL}"
    )

    return send_email(
        to_address=to_email,
        subject=f"{emoji} Your GlitchExecutor {tier_label} subscription is active",
        html_body=html,
        text_body=text,
    )


# ─── Email #2: Payment Failed ─────────────────────────────────────────────────

def send_payment_failed_email(to_email: str, tier: str = "Pro") -> bool:
    tier_label = tier.title()

    body = "".join([
        _info_box(
            "⚠️ We were unable to process your subscription payment. "
            "Your account has been <b>temporarily suspended</b> until payment is resolved.",
            "#ff6b35"
        ),
        _p("To restore access, please update your payment method:"),
        _ul([
            "Click the button below to open the billing portal",
            "Update your card or payment details",
            "Your account will be reactivated instantly",
        ]),
        _p(
            'If you think this is an error or need help, '
            f'reply to this email or contact us at '
            f'<a href="mailto:{EMAIL_FROM}" style="color:#00ff88;">{EMAIL_FROM}</a>.'
        ),
    ])

    html = _wrap(
        title="Payment failed — action required",
        body=body,
        cta_url=f"{SITE_URL}/billing",
        cta_label="Update Payment Method →",
    )

    text = (
        "Payment failed — action required\n\n"
        "We could not process your GlitchExecutor subscription payment.\n"
        "Your account has been temporarily suspended.\n\n"
        f"Update your payment: {SITE_URL}/billing\n\n"
        f"Need help? Email {EMAIL_FROM}"
    )

    return send_email(
        to_address=to_email,
        subject="⚠️ GlitchExecutor payment failed — update your card",
        html_body=html,
        text_body=text,
    )


# ─── Email #3: Subscription Cancelled ────────────────────────────────────────

def send_cancellation_email(to_email: str, tier: str = "Pro") -> bool:
    tier_label = tier.title()

    body = "".join([
        _p(
            f"Your <b>{tier_label}</b> subscription has been cancelled. "
            "Your account is now on the free trial tier — you can still access basic features."
        ),
        _info_box(
            "You can resubscribe at any time and pick up exactly where you left off. "
            "Your trade history and settings are saved.",
            "#888"
        ),
        _p("We'd love to know why you cancelled — your feedback helps us improve. "
           f'Reply to this email or reach us at '
           f'<a href="mailto:{EMAIL_FROM}" style="color:#00ff88;">{EMAIL_FROM}</a>.'),
    ])

    html = _wrap(
        title="Your subscription has been cancelled",
        body=body,
        cta_url=f"{SITE_URL}/#pricing",
        cta_label="Resubscribe →",
    )

    text = (
        "Your GlitchExecutor subscription has been cancelled.\n\n"
        "Your account is now on the free tier. You can resubscribe anytime.\n\n"
        f"Resubscribe: {SITE_URL}/#pricing\n"
        f"Feedback: {EMAIL_FROM}"
    )

    return send_email(
        to_address=to_email,
        subject="GlitchExecutor subscription cancelled",
        html_body=html,
        text_body=text,
    )


# ─── Email #4: Trial Ending Reminder ─────────────────────────────────────────

def send_trial_reminder_email(to_email: str, days_left: int = 2) -> bool:
    day_label = f"{days_left} day{'s' if days_left != 1 else ''}"
    urgency_color = "#ff6b35" if days_left <= 1 else "#f59e0b"

    body = "".join([
        _info_box(
            f"⏳ Your free trial ends in <b>{day_label}</b>. "
            "Upgrade now to keep your AI trading signals and analysis running without interruption.",
            urgency_color
        ),
        _p("Choose the plan that fits your trading style:"),
        _ul([
            "<b>⭐ Starter — $49/mo</b> · 30 analyses/day · BTC, ETH, SOL, XRP",
            "<b>🤖 Pro — $149/mo</b> · 100 analyses/day · All assets · Testnet auto-execution",
            "<b>🏢 Elite — $349/mo</b> · Unlimited · MT5 live bot on your VPS",
        ]),
        _p(
            "Not ready yet? You'll automatically drop to a read-only trial after it expires — "
            "no data is lost, and you can upgrade whenever you're ready."
        ),
    ])

    html = _wrap(
        title=f"Your trial ends in {day_label} — don't lose access",
        body=body,
        cta_url=f"{SITE_URL}/#pricing",
        cta_label=f"Upgrade Before Trial Ends →",
    )

    text = (
        f"Your GlitchExecutor trial ends in {day_label}.\n\n"
        "Upgrade to keep access:\n"
        f"  Starter $49/mo | Pro $149/mo | Elite $349/mo\n\n"
        f"{SITE_URL}/#pricing"
    )

    return send_email(
        to_address=to_email,
        subject=f"⏳ Your GlitchExecutor trial ends in {day_label}",
        html_body=html,
        text_body=text,
    )


# ─── Email #5: Newsletter / Lead Welcome ─────────────────────────────────────

def send_newsletter_welcome_email(to_email: str) -> bool:
    """Welcome email sent when someone submits the landing page email capture form."""

    body = "".join([
        _p("You're on the list. Here's what to expect:"),
        _ul([
            "<b>Weekly AI signal breakdowns</b> — what the ensemble spotted and why",
            "<b>Strategy guides</b> — how to get the most from 9-model consensus signals",
            "<b>Early access</b> to new models, features, and beta tools before anyone else",
        ]),
        _info_box(
            "<b>Want signals now?</b> Start your 7-day free trial — no commitment, "
            "cancel anytime. Your first AI analysis takes about 30 seconds to set up.",
            "#00ff88"
        ),
        _p(
            "Questions? Just reply to this email — we read every one."
        ),
    ])

    html = _wrap(
        title="You're in ⚡",
        body=body,
        cta_url=f"{SITE_URL}/#pricing",
        cta_label="Start My Free Trial →",
        footer_note=(
            f'You\'re receiving this because you subscribed at '
            f'<a href="{SITE_URL}" style="color:#00ff88;text-decoration:none;">glitchexecutor.com</a>.'
            f'&nbsp;|&nbsp;'
            f'<a href="{SITE_URL}/unsubscribe" style="color:#555;text-decoration:none;">Unsubscribe</a>'
        ),
    )

    text = (
        "You're in ⚡\n\n"
        "Thanks for signing up. Here's what's coming:\n"
        "- Weekly AI signal breakdowns\n"
        "- Strategy guides\n"
        "- Early access to new models and features\n\n"
        "Want signals now? Start your 7-day free trial:\n"
        f"{SITE_URL}/#pricing\n\n"
        "Questions? Just reply to this email."
    )

    return send_email(
        to_address=to_email,
        subject="You're in ⚡ — GlitchExecutor updates confirmed",
        html_body=html,
        text_body=text,
    )


# ─── Email #6: Trial Day 3 — Performance Proof ──────────────────────────────

def send_trial_day3_email(to_email: str, name: str = "trader",
                          performance: str = "") -> bool:
    """Day 3 trial email: live performance data alongside the Telegram message."""

    perf_block = _info_box(performance or "Check /performance in the bot for live data.", "#00ff88")

    body = "".join([
        _p(f"Hey {name},"),
        _p(
            "You're 3 days into your trial. Here's what our AI has been "
            "doing while you've been watching:"
        ),
        perf_block,
        _p(
            "This isn't a backtest. These are <b>live results</b> from the same "
            "system you're trialing."
        ),
        _p(
            "Want these signals to auto-execute on your account? "
            "Our Pro and Elite members don't lift a finger."
        ),
    ])

    html = _wrap(
        title="📊 Day 3: Real Numbers — No BS",
        body=body,
        cta_url=f"{SITE_URL}/#pricing",
        cta_label="See Plans →",
    )

    text = (
        f"Hey {name},\n\n"
        f"You're 3 days into your trial. Here's live performance data:\n\n"
        f"{performance or 'Check /performance in the bot'}\n\n"
        f"Want auto-execution? See plans: {SITE_URL}/#pricing"
    )

    return send_email(
        to_address=to_email,
        subject="📊 Day 3: Here's what our AI did this week",
        html_body=html,
        text_body=text,
    )


# ─── Email #7: Trial Day 5 — Plan Comparison ────────────────────────────────

def send_trial_day5_email(to_email: str, name: str = "trader",
                          checkout_url: str = "") -> bool:
    """Day 5 trial email: plan breakdown alongside the Telegram message."""

    body = "".join([
        _p(f"Hey {name},"),
        _p("Your trial ends in <b>2 days</b>. Here's what each plan gives you:"),
        _ul([
            "<b>⭐ Starter — $49/mo</b> · 30 AI analyses/day · Price alerts · Daily briefing",
            "<b>🤖 Pro — $149/mo</b> · 100 analyses/day · Auto-execute trades · Priority support",
            "<b>🏢 Elite — $349/mo</b> · Unlimited · MT5 bots on your VPS · 24/7 automation",
        ]),
        _info_box(
            "All plans save <b>20%</b> on yearly billing. "
            "Cancel anytime — your money stays in your broker account.",
            "#00ff88"
        ),
        _p(
            "❓ <b>Can I withdraw anytime?</b> Yes. Your money stays in your broker account.<br>"
            "❓ <b>What if the bot loses?</b> Every trade has a stop loss. Max drawdown target 8%.<br>"
            "❓ <b>Can I turn bots off?</b> Yes, full control anytime."
        ),
    ])

    html = _wrap(
        title="⚡ Day 5: Which Plan Fits You?",
        body=body,
        cta_url=checkout_url or f"{SITE_URL}/#pricing",
        cta_label="Choose Your Plan →",
    )

    text = (
        f"Hey {name},\n\n"
        f"Your trial ends in 2 days. Plans:\n"
        f"  Starter $49/mo | Pro $149/mo | Elite $349/mo\n\n"
        f"Choose: {checkout_url or f'{SITE_URL}/#pricing'}"
    )

    return send_email(
        to_address=to_email,
        subject="⚡ 2 days left — which plan fits you?",
        html_body=html,
        text_body=text,
    )
