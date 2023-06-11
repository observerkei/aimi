import os
from typing import List, Union, Any, Dict

from tool.config import config
from tool.util import log_dbg, log_err, log_info, write_yaml

class Memory:
    openai_conversation_id: str = ''
    memory_model_type: str = 'transformers'
    meomry_model_file: str = ''
    model_enable: bool = False
    idx: int = 0
    size: int = 1024
    pool: List[dict] = []
    memory_model: Any
    memory_model_depth: int = 20

    def __init__(self):
        self.__load_memory()

        if self.memory_model_type == 'transformers':
            try:
                from tool.transformer import Transformers
                self.memory_model = Transformers()
                self.model_enable = True
            except Exception as e:
                log_err(f'fail to load Transformers: {e}')
                self.memory_model = None
                self.model_enable = False

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
        try:
            self.memory_model_type = config.setting['aimi']['memory_model']
        except:
            self.memory_model_type = 'transformers'

        self.memory_model_file = config.memory_model_file 

        try:
            self.memory_model_depth = config.setting['aimi']['memory_model_depth']
        except:
            self.memory_model_depth = 20
        
        if len(self.pool) < self.size:
            self.pool.extend([None] * (self.size - len(self.pool)))
        if self.idx > self.size:
            self.idx = 0

        # fix pool idx
        end_idx = 0
        for talk_item in reversed(self.pool):
            if not talk_item:
                end_idx += 1
                continue
            break

        shold_idx = self.size - end_idx
        log_dbg("shold_idx: " + str(shold_idx))
        log_dbg('idx: ' + str(self.idx))
        if shold_idx != self.idx:
            log_info('idx:{} fix to {}'.format(self.idx, shold_idx))
            self.idx = shold_idx

        log_dbg('conv_id: ' + str(self.openai_conversation_id))
        log_dbg('size: ' + str(self.size))
       
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
            ret = True

        except Exception as e:
            log_err('fail to save memory: {}, file:{}'.format(str(e), save_path))
            ret = False

        # ret |= self.__save_model()

        return ret

    def __get_memory(self, question: str) -> Union[str, List[dict]]:
        valid_talk_items: List[dict] = []
        
        range_target = self.idx

        # add history right
        for talk_item in self.pool[range_target:]:
            if talk_item:
                valid_talk_items.append(talk_item)
        # add history left
        for talk_item in self.pool[:range_target]:
            if talk_item:
                valid_talk_items.append(talk_item)

        return valid_talk_items

    def dream(self):
        ret = self.__train_model()
        log_info('have a dream done')
        return ret

    def search(
        self,
        question: str,
        max_size: int = 1024
    ) -> str:

        history = ''

        # use memory_model
        talk_history: List[Dict] = []
        talk_history_append = 0
        def qa_dict_to_list(pool_qa, talk_list, talk_list_append, max_size=max_size):
            for item in pool_qa:
                q = item.get('q', None)
                a = item.get('a', None)
                if q and a:
                    talk_prefix = '0 我说:“”\n'
                    append_len = len(str(talk_list)) + len(q) + len(a) + 2*len(talk_prefix) + len(question)
                    
                    log_dbg('now len: ' + str(append_len))
                    
                    if append_len > max_size:
                        log_dbg('replay over limit. now openai_input len: ' + str(append_len))
                        append_len = len(str(talk_list)) + len(q) + len(talk_prefix) + len(question)
                        if append_len > max_size:
                            log_dbg('replay over limit. skip history. len: ' + str(append_len))
                            break
                    
                        log_dbg('replay over limit, append pre question.')
                        talk_history.insert(talk_list_append, {'role': 'user', 'content': q})
                        continue
                    # 0 是设定 先放回答再放提问，这样顺序反过来
                    talk_history.insert(talk_list_append, { 'role': 'assistant', 'content': a})
                    talk_history.insert(talk_list_append, { 'role': 'user', 'content': q})
            return talk_history

        # 倒着插入的，所以要把历史放在前面插入
        if self.model_enable:
            recall_items = self.__predict_model(question)
            log_dbg('model search: ' + str(recall_items))
            talk_history = qa_dict_to_list(recall_items, talk_history, talk_history_append, max_size/2)

        # 将model 的数据放在最前面。
        talk_history_append = len(talk_history)
        talk_items = self.__get_memory(question)
        talk_history = qa_dict_to_list(reversed(talk_items), talk_history, talk_history_append)

        return talk_history

    def make_history(
        self,
        talk_history: List[Dict]
    ) -> str:
        history = ''

        talk_count = 0
        for talk in talk_history:
            content = ''
            it = ''
            for k, v in talk.items():
                if k == 'role' and v == 'user':
                    talk_count += 1
                    it = '我说:'
                    continue
                if k == 'role' and v == 'assistant':
                    it = '你说:'
                if k != 'content':
                    continue
                content = v
            history += f'{talk_count} {it} {content}\n'
        # todo
        return history


    def __model_enable(self) -> bool:
        return len(self.memory_model_type)

    def __train_model(self):
        if self.model_enable:
            return self.memory_model.train(self.pool, self.memory_model_depth)

    def __predict_model(self, question: str) -> List[dict]:
        if self.model_enable:
            return self.memory_model.predict(question, predict_limit=3)
        return []

    def __load_model(self):
        try:
            if self.model_enable:
                ret = self.memory_model.load_model(self.memory_model_file)
                if not ret:
                    log_err('fail to laod memory: ' + str(self.memory_model_file))
                    return False

                log_info('load memory done: ' + str(self.memory_model_file))
                return True

        except Exception as e:
            log_err('fail to load: ' + str(self.memory_model_file) + ' ' + str(e))
            return False

        return True

    def __save_model(self):
        try:
            if self.model_enable:
                ret = self.memory_model.save_model(self.memory_model_file)
                if not ret:
                    log_err('fail to save memory: ' + str(self.memory_model_file))
                    return False

                log_info('save memory done: ' + str(self.memory_model_file))
                return True

        except Exception as e:
            log_err('fail to save: ' + str(self.memory_model_file) + ' ' + str(e))
            return False

        return True
 
    def append(self, q: str, a: str):
        if not self.need_memory(a):
            log_info('no need save memory.')
            return

        next_idx = self.__get_next_idx()
        talk_item = {
            'q': q,
            'a': a,
            'idx': next_idx
        }
        log_dbg('append memory: ' + str(talk_item))
        self.pool[self.idx] = talk_item
        self.idx = self.__get_next_idx()

    def need_memory(self, a: str) -> bool:
        if ('OpenAI' in a) or ('ChatGPT' in a):
            if '使用政策' in a:
                return False
            if '道德准则' in a:
                return False
            if '法律限制' in a:
                return False
            if '技术限制' in a:
                return False
        return True

    def __get_next_idx(self) -> int:
        if (self.idx >= (self.size - 1)):
            return 0
        return self.idx + 1
    
memory = Memory()
