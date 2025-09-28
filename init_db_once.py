# init_db_once.py
import store, os
print("[*] DB_PATH =", store.DB_PATH)
store.init_db()
print("[*] Initialized. Tables should exist now.")
