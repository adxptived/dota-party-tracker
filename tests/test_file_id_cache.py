"""B7: картинка, которую уже отправляли, второй раз уходит по file_id — без повторной загрузки PNG."""
import asyncio
from types import SimpleNamespace

import pytest
from aiogram.types import BufferedInputFile

import mmrbot.bot as botmod
from mmrbot.boards import ImageBoard


def run(coro):
    return asyncio.run(coro)


class Chat:
    id = 5


class Msg:
    """Сообщение-фото: answer_photo возвращает отправленное сообщение с file_id, как настоящий aiogram."""

    def __init__(self, reject_ids=False):
        self.chat, self.photo = Chat(), [object()]
        self.sent, self.edits, self.reject_ids, self.n = [], [], reject_ids, 0

    def _reply(self):
        self.n += 1
        return SimpleNamespace(photo=[SimpleNamespace(file_id="small"), SimpleNamespace(file_id=f"FID{self.n}")])

    async def answer_photo(self, photo, caption=None, **kw):
        if self.reject_ids and isinstance(photo, str):
            raise RuntimeError("Bad Request: wrong file identifier/HTTP URL specified")
        self.sent.append(photo)
        return self._reply()

    async def edit_media(self, media, reply_markup=None, **kw):
        if self.reject_ids and isinstance(media.media, str):
            raise RuntimeError("Bad Request: wrong file identifier/HTTP URL specified")
        self.edits.append(media.media)
        return self._reply()

    async def answer(self, text, **kw):
        self.sent.append(text)

    async def delete(self):
        pass


@pytest.fixture(autouse=True)
def clean():
    botmod._file_ids.clear()


def board(png=b"\x89PNG-one"):
    return ImageBoard("текст", png=png, caption="подпись")


def test_second_send_uses_file_id():
    msg = Msg()
    run(botmod._reply_image(msg, board(), None, edit=False))
    run(botmod._reply_image(msg, board(), None, edit=False))
    assert isinstance(msg.sent[0], BufferedInputFile)
    assert msg.sent[1] == "FID1"  # самый крупный размер фото


def test_other_picture_is_uploaded_again():
    msg = Msg()
    run(botmod._reply_image(msg, board(b"\x89PNG-a"), None, edit=False))
    run(botmod._reply_image(msg, board(b"\x89PNG-b"), None, edit=False))
    assert all(isinstance(p, BufferedInputFile) for p in msg.sent)


def test_tab_switch_back_edits_by_file_id():
    msg = Msg()
    run(botmod._reply_image(msg, board(b"\x89PNG-a"), None, edit=True))
    run(botmod._reply_image(msg, board(b"\x89PNG-b"), None, edit=True))
    run(botmod._reply_image(msg, board(b"\x89PNG-a"), None, edit=True))
    assert isinstance(msg.edits[0], BufferedInputFile) and isinstance(msg.edits[1], BufferedInputFile)
    assert msg.edits[2] == "FID1"


def test_rejected_file_id_falls_back_to_upload_and_is_forgotten():
    msg = Msg()
    run(botmod._reply_image(msg, board(), None, edit=False))
    msg.reject_ids = True
    run(botmod._reply_image(msg, board(), None, edit=False))
    assert isinstance(msg.sent[-1], BufferedInputFile)  # устаревший file_id не оставил чат без картинки
    msg.reject_ids = False
    run(botmod._reply_image(msg, board(), None, edit=False))
    assert msg.sent[-1] == "FID2"  # после успешной загрузки id снова запомнен


def test_cache_is_bounded():
    msg = Msg()
    botmod.FILE_ID_LIMIT, old = 3, botmod.FILE_ID_LIMIT
    try:
        for n in range(6):
            run(botmod._reply_image(msg, board(f"\x89PNG-{n}".encode()), None, edit=False))
    finally:
        botmod.FILE_ID_LIMIT = old
    assert len(botmod._file_ids) <= 3


def test_fakes_without_return_value_still_work():
    class Plain(Msg):
        async def answer_photo(self, photo, caption=None, **kw):
            self.sent.append(photo)
            return None

    msg = Plain()
    run(botmod._reply_image(msg, board(), None, edit=False))
    run(botmod._reply_image(msg, board(), None, edit=False))
    assert all(isinstance(p, BufferedInputFile) for p in msg.sent)
