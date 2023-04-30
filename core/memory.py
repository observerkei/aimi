import os
from typing import List, Union

from tool.config import config
from tool.util import log_dbg, log_err, log_info, write_yaml

class Memory:
    openai_conversation_id: str = ''
    idx: int = 0
    size: int = 1024
    pool: List[dict] = []

    def __init__(self):
        self.__load_memory()
    
    def __load_memory(self):
        mem = config.load_memory()
        try:
            self.pool = mem['pool']
        except:
            self.pool = []
        try:
            self.openai_conversation_id = mem['openai_conversation_id']
        except:
            self.openai_conversation_id = ''
        try:
            self.idx = mem['idx']
        except:
            self.idx = 0
        try:
            self.size = config.setting['aimi']['memory_size']
        except:
            self.size = 1024
        
        if len(self.pool) < self.size:
            self.pool.extend([None] * (self.size - len(self.pool)))
        if self.idx > self.size:
            self.idx = 0

        log_dbg('conv_id: ' + str(self.openai_conversation_id))
        log_dbg('size: ' + str(self.size))
        log_dbg('idx: ' + str(self.idx))
        for iter in self.pool:
            if iter:
                log_dbg('pool: ' + str(iter))
        
    def save_memory(self) -> bool:

        save_path = config.memory_config

        try:
            save_dir = os.path.dirname(save_path)
            if save_dir != '.' and not os.path.exists(save_dir):
                os.makedirs(save_dir)

            save_obj = {
                'openai_conversation_id': self.openai_conversation_id,
                'idx': self.idx,
                'pool': self.pool
            }

            write_yaml(save_path, save_obj)

            log_info('save memory done: ' + str(save_path))
            
            return True

        except Exception as e:
            log_err('fail to save memory:{}, file:{}'.format(str(e), save_path))
            return False

    def __get_memory(self, question: str) -> Union[str, List[dict]]:
        valid_talk_items: List[dict] = []
        
        cur_index = self.idx
        max_length = self.size
        range_target = cur_index

        # add history right
        for talk_item in self.pool[range_target:]:
            if talk_item:
                valid_talk_items.append(talk_item)
        # add history left
        for talk_item in self.pool[:range_target]:
            if talk_item:
                valid_talk_items.append(talk_item)

        return valid_talk_items

    def search(
        self,
        question: str,
        max_size: int = 1024
    ) -> str:

        history = ''
        
        talk_count = 0
        talk_items = self.__get_memory(question)
        talk_history: List[str] = []
        for item in reversed(talk_items):
            q = item.get('q', None)
            a = item.get('a', None)
            if q and a:
                talk_prefix = '0 我说:“”\n'
                append_len = len(str(talk_history)) + len(q) + len(a) + 2*len(talk_prefix) + len(question)

                log_dbg('now len: ' + str(append_len))

                if append_len > max_size:
                    log_dbg('replay over limit. now openai_input len: ' + str(append_len))
                    append_len = len(str(talk_history)) + len(q) + len(talk_prefix) + len(question)
                    if append_len > max_size:
                        log_dbg('replay over limit. skip history.')
                        break
                    else:
                        log_dbg('replay over limit, append pre question.')
                        talk_history.insert(0, '我说:“{}”\n'.format(q))
                        continue
                # 0 是设定 先放回答再放提问，这样顺序反过来
                talk_history.insert(0, '你说:“{}”\n'.format(a))
                talk_history.insert(0, '我说:“{}”\n'.format(q))
                
        for item in talk_history:
            if '我说' in item:
                talk_count += 1
            history += '{} {}'.format(talk_count, item)

        return history
    
    def append(self, q: str, a: str):
        talk_item = {
            'q': q,
            'a': a
        }
        log_dbg('append: ' + str(talk_item))
        self.pool[self.idx] = talk_item
        self.idx = self.__get_next_idx()
        
    def __get_next_idx(self) -> int:
        return (self.idx + 1) % self.size
    
memory = Memory()
