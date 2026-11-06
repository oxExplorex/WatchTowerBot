import zipfile

import pytest

from core.backup_format import InvalidBackup
from core.media_store import MediaStore
from core.personal_crypto import create_key_bundle
from db.repositories.personal_repo import PersonalKeyRepository
from services.backup_restore import prepare_backup
from services.chat_dump import chat_accounts, create_chat_dump


@pytest.mark.asyncio
async def test_zip_dump_is_scoped_to_one_owner_account_and_chat(db_main, tmp_path):
    await PersonalKeyRepository(db_main.get_session_factory).install(123, create_key_bundle(123, "СекретДампа123"))
    for owner, account, chat in ((123, 456, 789), (123, 456, 790), (123, 457, 789), (999, 456, 789)):
        await db_main.messages_repository.record(owner_id=owner, account_user_id=account, chat_id=chat,
            message_id=1, kind="new", source="business", event_key="one",
            payload={"text": f"private-{owner}-{account}-{chat}", "media": []})
    assert await chat_accounts(123, 789, session_factory=db_main.get_session_factory) == [456, 457]
    path, counts = await create_chat_dump(123, 456, 789, tmp_path / "dump",
        session_factory=db_main.get_session_factory, store=MediaStore(tmp_path / "media"))
    assert path.suffix == ".zip" and counts["messages"] == 1
    paths = []
    with zipfile.ZipFile(path) as archive:
        for index, name in enumerate(archive.namelist()):
            content = archive.read(name)
            assert b"private-123-456-789" not in content
            target = tmp_path / f"part{index}.wtb"
            target.write_bytes(content)
            paths.append(target)
    prepared = prepare_backup(paths, tmp_path / "read", 123, "СекретДампа123")
    messages = [row for table, row in prepared.rows if table == "messages"]
    assert [(row.owner_id, row.account_user_id, row.chat_id) for row in messages] == [(123, 456, 789)]
    assert all(row.chat_id == 789 and row.account_user_id == 456 for table, row in prepared.rows if table == "events")
    with pytest.raises(InvalidBackup):
        await create_chat_dump(123, 456, 99999, tmp_path / "forged",
            session_factory=db_main.get_session_factory, store=MediaStore(tmp_path / "media"))
