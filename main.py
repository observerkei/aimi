from tool.config import config
from tool.openai_api import openai_api
from tool.util import log_dbg, log_err  

from core.aimi import aimi
from core.memory import memory

while True:
    question = input('please input question:')
    if 'exit()' in question:
        break
    answer = {}
    for msg in aimi.ask(
        question
    ):
        answer = msg
        log_dbg(str(answer))

