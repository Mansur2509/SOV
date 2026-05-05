"""safe_edit_text и safe_answer_or_edit."""
import logging
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)

async def safe_edit_text(message, text: str, **kwargs):
    try:
        await message.edit_text(text, **kwargs)
    except TelegramBadRequest as e:
        err = str(e).lower()
        if "message is not modified" in err:
            pass
        elif "there is no text in the message" in err:
            try: await message.answer(text, **kwargs)
            except Exception: pass
        else:
            logger.warning(f"safe_edit_text: {e}")
    except Exception as e:
        logger.warning(f"safe_edit_text unexpected: {e}")

async def safe_answer_or_edit(call, text: str, **kwargs):
    try:
        await call.message.edit_text(text, **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            pass
        else:
            try: await call.message.answer(text, **kwargs)
            except Exception: pass
    except Exception:
        try: await call.message.answer(text, **kwargs)
        except Exception: pass
