from typing import Dict, Any, List, Generator, Optional, Union, Set
from tool.util import log_dbg

def log_dbg(s):
    pass

class JsonStreamDataType:
    ARR = "arr"
    BOL = "bol"
    OBJ = "obj"
    NUM = "num"
    NUL = "nul"
    STR = "str"
    UND = "und"
    ALL = ["arr", "bol", "obj", "num", "nul", "str"]


class JsonStreamData:
    type: str
    data: Any
    done: bool = False
    path: str

    now_arr_cnt = 0
    now_key = ""
    key_start = 0
    key_end = 0
    colon_offset = 0
    val_start = 0
    val_end = 0

    def str(self):
        if self.type == JsonStreamDataType.ARR:
            cnt = 0
            for i in self.data:
                i: "JsonStreamData"
                log_dbg(f"path: {i.path}, {i.str()}")
        elif self.type == JsonStreamDataType.OBJ:
            for k, v in self.data.items():
                v: "JsonStreamData"
                log_dbg(f"path: {v.path}, k: {k}, v: {v.str()}")
        else:
            return str(self.data)

    def __init__(self, type, path) -> None:
        self.reset(type, path)

    def reset(self, type, path):

        self.type = type
        self.path = path

        if type == JsonStreamDataType.ARR:
            self.data = []
        elif type == JsonStreamDataType.BOL:
            self.data = False
        elif type == JsonStreamDataType.OBJ:
            self.data = {}
        elif type == JsonStreamDataType.NUM:
            self.data = 0
        elif type == JsonStreamDataType.NUL:
            self.data = None
        elif type == JsonStreamDataType.STR:
            self.data = ""
        else:
            self.data = None

        self.type_parser_reset()

    def type_parser_reset(self):
        log_dbg(f"clear {self.type}: {self.now_key} parser cache. ")
        self.now_key = ""
        self.key_start = 0
        self.key_end = 0
        self.colon_offset = 0
        self.val_start = 0
        self.val_end = 0


class JsonStream:
    done = False
    path = "json"

    buf: str = ""
    offset: int = 0
    stream_map: Dict[str, JsonStreamData]

    def __init__(self):
        self.stream_map = {}
        self.stream_map[self.path] = JsonStreamData(JsonStreamDataType.UND, self.path)

    def is_path(self, path=""):
        if self.path == path:
            return True
        return False

    def path_data(self):
        return self.stream_map[self.path].data

    def parser(self, buf: str):
        self.buf += buf

        now_path = self.path
        now_stream = self.stream_map[self.path]
        log_dbg(f"path: {self.path}")

        cur = len(self.buf) - self.offset

        while cur and now_stream:
            cur -= 1

            for sub_stream in self.parser_buf(stream=now_stream, path=now_path):
                if not sub_stream:
                    break

                now_path = sub_stream.path

                if self.offset >= len(self.buf):
                    break

                log_dbg(
                    f"now_path: {self.path}, type: {now_stream.type}, buf: {self.buf[self.offset:]}"
                )

                if sub_stream.done:
                    break

            if (
                now_stream
                and now_stream.type != JsonStreamDataType.ARR
                and now_stream.type != JsonStreamDataType.OBJ
                and now_stream.type != JsonStreamDataType.UND
            ):
                yield now_stream

            if now_stream and now_stream.done:
                now_stream = self.parser_stream_done(now_stream)


    def parser_stream_done(self, stream: JsonStreamData):
        log_dbg(f"check done type: {stream.type}, data: {str(stream.data)}")
        if not stream.done:
            return stream

        log_dbg(
            f"path: {self.path}, type: {stream.type}, "
            f"offset: {self.offset}, all: {len(self.buf)}, stream done. "
        )

        parent_path_end = self.path.rfind("[")
        if -1 != parent_path_end:
            parent_path = self.path[:parent_path_end]
            parent = self.stream_map[parent_path]

            if parent.type == JsonStreamDataType.OBJ:
                log_dbg(f"del path: {self.path[parent_path_end:]}")
                parent.type_parser_reset()
                del self.stream_map[self.path]
                self.path = parent_path
            elif parent.type == JsonStreamDataType.ARR:
                log_dbg(f"del path: {self.path[parent_path_end:]}")
                del self.stream_map[self.path]
                self.path = parent_path

        stream.type_parser_reset()

        # root json
        if self.path == "json":
            return stream

    def get_parser_type(self, buf, offset):
        if offset >= len(buf):
            return JsonStreamDataType.UND

        parser_type = {
            "{": JsonStreamDataType.OBJ,
            "[": JsonStreamDataType.ARR,
            '"': JsonStreamDataType.STR,
            "t": JsonStreamDataType.BOL,
            "f": JsonStreamDataType.BOL,
            "n": JsonStreamDataType.NUL,
        }
        for num in range(0, 10):
            parser_type[str(num)] = JsonStreamDataType.NUM
            parser_type[num] = JsonStreamDataType.NUM
        parser_type["-"] = JsonStreamDataType.NUM

        type = parser_type.get(buf[offset])
        if type not in JsonStreamDataType.ALL:
            return JsonStreamDataType.UND

        log_dbg(f"type: {type}")

        return type

    def parser_buf(self, stream: JsonStreamData, path):
        parser_hook = {
            JsonStreamDataType.OBJ: self.parser_obj,
            JsonStreamDataType.ARR: self.parser_arr,
            JsonStreamDataType.STR: self.parser_str,
            JsonStreamDataType.NUM: self.parser_num,
            JsonStreamDataType.BOL: self.parser_bol,
            JsonStreamDataType.NUL: self.parser_nul,
        }
        if stream.type in JsonStreamDataType.ALL:
            hook = parser_hook.get(stream.type)
            yield from hook(stream, path)
        else:
            yield from self.parser_und(stream, path)

    def parser_und(self, stream: JsonStreamData, path):
        # 未定义场景, 表示还没开始处理数据. 所以现在进行尝试.
        type = self.get_parser_type(self.buf, self.offset)
        log_dbg(f"path: {path}, stream_type: {stream.type}, type: {type}")
        if type not in JsonStreamDataType.ALL:
            log_dbg(
                f"cannot parser path({path}), type: {str(type)}, "
                f"offset: {self.offset}, all: {len(self.buf)} buf: {self.buf[self.offset:]}"
            )
            yield stream
        else:
            stream.reset(type, path)
            log_dbg(f"new stream type: {stream.type}")

            if type == JsonStreamDataType.ARR:
                self.offset += 1  # 跳过生成过的字符.
                self.path = f"{path}.arr"
                self.stream_map[self.path] = stream
            elif type == JsonStreamDataType.OBJ:
                self.offset += 1  # 跳过生成过的字符.
                self.path = f"{path}.obj"
                self.stream_map[self.path] = stream
            elif type == JsonStreamDataType.STR:
                self.offset += 1  # 跳过生成过的字符.
            else:
                pass

            yield from self.parser_buf(stream, path)

    def parser_obj(self, obj_stream: JsonStreamData, path):
        cur = len(self.buf) - self.offset
        while cur and self.offset < len(self.buf):
            cur -= 1

            log_dbg(
                f"try parser: {self.buf[self.offset]}, now_offset: {self.offset}, all: {len(self.buf)}"
            )

            if not obj_stream.key_start:
                if self.buf[self.offset] == '"':
                    obj_stream.key_start = self.offset + 1
                    log_dbg(f"start: {obj_stream.key_start}")
                self.offset += 1
                continue

            if not obj_stream.key_end:
                if self.buf[self.offset] == '"' and self.is_str_val_end(
                    self.buf, self.offset
                ):
                    obj_stream.key_end = self.offset
                    log_dbg(f"end: {obj_stream.key_end}")
                self.offset += 1
                continue

            obj_stream.now_key = self.buf[obj_stream.key_start : obj_stream.key_end]
            log_dbg(f"key: {obj_stream.now_key}")

            new_path = f'{path}["{obj_stream.now_key}"]'

            if not obj_stream.colon_offset:
                if self.buf[self.offset] == ":":
                    obj_stream.colon_offset = self.offset
                self.offset += 1
                continue

            if self.buf[self.offset] == " ":
                self.offset += 1
                continue

            log_dbg(
                f"self.offset: {self.offset}, len: {len(self.buf)}, "
                f"key: {obj_stream.now_key}, val: {self.buf[self.offset:]}"
            )

            stream = JsonStreamData(JsonStreamDataType.UND, new_path)
            for sub_stream in self.parser_buf(stream, new_path):
                if not sub_stream:
                    break

                # 解析完成了一个 key. 正在解析 val 中.
                if obj_stream.now_key not in obj_stream.data:
                    obj_stream.data[obj_stream.now_key] = sub_stream

                    # 记录正在解析的路径信息.
                    if new_path not in self.stream_map:
                        self.stream_map[new_path] = sub_stream
                        self.path = new_path

                log_dbg(
                    f"send type: {sub_stream.type}, data: {str(sub_stream.data)}, done: {str(sub_stream.done)}"
                )

                yield sub_stream

            if self.offset >= len(self.buf):
                break

            if self.buf[self.offset] == ",":
                stream.done = True
                self.offset += 1
                yield stream
                continue

            # 到了尾声, 如果结束了的话, 就设置完成.
            if self.buf[self.offset] == "}" and self.is_str_val_end(
                self.buf, self.offset
            ):
                obj_stream.done = True
                self.offset += 1
                break

        yield obj_stream

    def parser_arr(self, arr_stream: JsonStreamData, path):
        cur = len(self.buf) - self.offset

        while cur and self.offset < len(self.buf):
            cur -= 1

            log_dbg(f"cur: {cur}, offset: {self.offset}, all: {len(self.buf)}")

            if self.buf[self.offset] == " ":
                self.offset += 1
                continue

            new_path = f"{path}[{arr_stream.now_arr_cnt}]"
            stream = JsonStreamData(JsonStreamDataType.UND, new_path)

            for item_stream in self.parser_buf(stream, new_path):
                if not item_stream:
                    break
                log_dbg(
                    f"path: {new_path}, item type: {item_stream.type}, item_data: {item_stream.str()}"
                )

                arr_data: List[JsonStreamData] = arr_stream.data
                if len(arr_stream.data) < arr_stream.now_arr_cnt + 1:
                    arr_data.append(item_stream)
                    if new_path not in self.stream_map:
                        self.stream_map[new_path] = item_stream
                        self.path = new_path
                else:
                    arr_data[arr_stream.now_arr_cnt] = item_stream

                yield item_stream

                if item_stream.done:
                    break

            if self.offset >= len(self.buf):
                break

            if self.buf[self.offset] == " ":
                self.offset += 1
                continue

            if self.buf[self.offset] == ",":
                arr_stream.now_arr_cnt += 1
                self.offset += 1
                continue

            if self.buf[self.offset] == "]":
                arr_stream.done = True
                self.offset += 1
                break

        yield arr_stream

    def parser_num(self, num_stream: JsonStreamData, path):
        if not num_stream.val_start:
            num_stream.val_start = self.offset
        cur = len(self.buf) - self.offset
        log_dbg(
            f"offset: {self.offset}, all: {len(self.buf)}, buf: {self.buf[self.offset:]}"
        )

        while cur and self.offset < len(self.buf):
            cur -= 1
            ch = self.buf[self.offset]
            if ch == "," or ch == "]" or ch == "}":
                num_stream.val_end = self.offset
                num = self.buf[num_stream.val_start : num_stream.val_end]
                log_dbg(
                    f"num: {str(num)}, offset: {self.offset}, all: {len(self.buf)}, buf: {self.buf[self.offset:]}"
                )
                num_stream.data = int(num)
                num_stream.done = True

                break

            self.offset += 1

        yield num_stream

    def parser_nul(self, nul_stream: JsonStreamData, path):
        if not nul_stream.val_start:
            nul_stream.val_start = self.offset
        cur = len(self.buf) - self.offset

        while cur and self.offset < len(self.buf):
            cur -= 1

            ch = self.buf[self.offset]
            if ch == "," or ch == "]" or ch == "}":
                nul_stream.val_end = self.offset
                nul = self.buf[nul_stream.val_start : nul_stream.val_end]
                if "null" != nul:
                    raise Exception(f"data not null: {self.buf}")
                nul_stream.data = None

                nul_stream.done = True

                break

            self.offset += 1

        yield nul_stream

    def parser_bol(self, bol_stream: JsonStreamData, path):
        if not bol_stream.val_start:
            bol_stream.val_start = self.offset
        end = 0
        cur = len(self.buf) - self.offset

        while cur and self.offset < len(self.buf):
            cur += 1

            ch = self.buf[self.offset]
            if ch == "," or ch == "]" or ch == "}":
                bol_stream.val_end = self.offset
                bol = self.buf[bol_stream.val_start : bol_stream.val_end]

                if bol == "true":
                    bol_stream.data = True
                else:
                    bol_stream.data = False
                bol_stream.done = True

                break

            self.offset += 1

        yield bol_stream

    def parser_str(self, str_stream: JsonStreamData, path):
        cur = len(self.buf) - self.offset
        while cur and self.offset < len(self.buf):
            cur -= 1

            log_dbg(
                f"system_path: {self.path} path: {path}. try get str, "
                f"offset: {self.offset}, val: {self.buf[self.offset:]}"
            )

            if self.buf[self.offset] == '"' and (
                self.is_str_val_end(self.buf, self.offset)
            ):
                self.offset += 1
                str_stream.done = True
                log_dbg(f"str parset val done: {str_stream.data}")
                break

            add_str = self.buf[self.offset]
            str_stream.data += add_str

            self.offset += 1

            yield str_stream

        yield str_stream

    def is_str_val_end(self, buf, now_offset):
        now = buf[now_offset]
        log_dbg(f"check end: {now}")

        if buf[now_offset - 1] == "\\":
            if buf[now_offset - 2] == "\\":
                if buf[now_offset - 3] == "\\":
                    if buf[now_offset - 4] == "\\":
                        # \\ \\ " end
                        return True
                    else:
                        # ? \\ \" continue
                        return False
                else:
                    # ? \\ " end
                    return True
            else:
                # ?\" continue
                return False
        else:
            # 前面不是 \ , 这里收到了 " 说明 json val 结束
            return True


if __name__ == "__main__":
    json_stream = JsonStream()
    rsp_data = '[{"type": "object", "timestamp": 4, "expect": "你好", "reasoning": "AimiCore开始思考: 根据Master的指示，回复`你好`。", "call": "chat_to_master", "request": {"type": "object", "content": "[AimiCore] 你好，我已经初始化完成。", "from": [2]}, "conclusion": "为了符合Guidance，我回复了`你好`。", "execute": "system"}]'

    import time

    for s in iter(rsp_data):
        for stream in json_stream.parser(s):
            data = json_stream.path_data()
            print(f"path:{stream.path}: {str(data)}, done: {stream.done}")
            continue

    # for k, v in json_stream.stream_map.items():
    #     log_dbg(f"=====")
    #     log_dbg(f"{k}: {v.str()}")
