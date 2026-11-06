from aiogram.fsm.state import State, StatesGroup


class BackupImport(StatesGroup):
    files = State()
    secret = State()
    chat_id = State()


IMPORT_FILES = BackupImport.files.state
IMPORT_SECRET = BackupImport.secret.state
IMPORT_STATES = {IMPORT_FILES, IMPORT_SECRET}
DUMP_CHAT_ID = BackupImport.chat_id.state
