from typing import Dict, Any, List, Generator, Optional, Union, Set
from tool.util import log_dbg
import codecs


def log_dbg(f):
    pass


class JsonStreamRoot:
    Root = "json"


class JsonStreamDataType:
    ARR = "arr"
    BOL = "bol"
    OBJ = "obj"
    NUM = "num"
    NUL = "nul"
    STR = "str"
    UND = "und"
    ALL = {"arr": 0, "bol": 0, "obj": 0, "num": 0, "nul": 0, "str": 0}


class JsonStreamData:
    type: str
    __data: Any = ""
    done: bool = False
    path: str
    chunk: Any = ""

    parent: "JsonStreamData"

    now_arr_cnt = 0
    now_key = ""
    key_start = 0
    key_end = 0
    colon_offset = 0
    val_start = 0
    val_end = 0

    def set_data(self, val):
        self.__data = val

    def len(self):
        if self.type == JsonStreamDataType.BOL or (
            self.type == JsonStreamDataType.NUL
            or self.type == JsonStreamDataType.NUM
            or self.type == JsonStreamDataType.UND
        ):
            return None

        if not self.__data:
            return None

        return len(self.data)

    def str(self):
        if self.type == JsonStreamDataType.ARR:
            res = f"arr path: {self.path} {{ "
            cnt = 0
            for i in self.__data:
                i: "JsonStreamData"
                if cnt != 0:
                    res += ","
                res += f" {cnt}: {i.str()}"
                cnt += 1
            return res + " }"
        elif self.type == JsonStreamDataType.OBJ:
            res = f"obj path: {self.path} {{"
            cnt = 0
            for k, v in self.__data.items():
                v: "JsonStreamData"
                if cnt != 0:
                    res += ","
                res += f' "{k}": {v.str()}'
                cnt += 1
            return res + " }"
        else:
            return str(self.__data)

    @property
    def data(self):
        if self.type == JsonStreamDataType.ARR:
            arr = []
            for item in self.__data:
                item: "JsonStreamData"
                arr.append(item.data)
            return arr
        elif self.type == JsonStreamDataType.OBJ:
            dict = {}
            for k, v in self.__data.items():
                v: "JsonStreamData"
                dict[k] = v.data
            return dict

        return self.__data

    @property
    def stream_data(self) -> "JsonStreamData":
        return self.__data

    def __init__(self, type, path) -> None:
        self.reset(type)
        self.path = path

    def reset(self, type):

        self.type = type
        self.done = False
        self.now_arr_cnt = 0

        if type == JsonStreamDataType.ARR:
            self.__data = []
        elif type == JsonStreamDataType.BOL:
            self.__data = False
        elif type == JsonStreamDataType.OBJ:
            self.__data = {}
        elif type == JsonStreamDataType.NUM:
            self.__data = 0
        elif type == JsonStreamDataType.NUL:
            self.__data = None
        elif type == JsonStreamDataType.STR:
            self.__data = ""
        else:
            self.__data = None

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
    done: bool = False
    path = JsonStreamRoot.Root

    buf: str = ""
    offset: int = 0
    stream_map: Dict[str, JsonStreamData]

    def __init__(self):
        self.stream_map = {}
        stream = JsonStreamData(JsonStreamDataType.UND, self.path)
        stream.parent = stream
        self.stream_map[JsonStreamRoot.Root] = stream

    def is_path(self, path=""):
        if self.path == path:
            return True
        return False

    def need_skip_char(self, ch) -> bool:
        if ch == " " or ch == "\n" or ch == "\t":
            return True
        return False

    @property
    def data(self):
        return self.root_stream.data

    @property
    def path_data(self):
        return self.stream_map[self.path].data

    @property
    def root_stream(self):
        return self.stream_map[JsonStreamRoot.Root]

    def parser(self, buf: str):
        if isinstance(buf, str):
            self.buf += buf

        now_stream = self.stream_map[self.path]
        log_dbg(f"path: {self.path}")

        cur = len(self.buf) - self.offset

        while cur and self.offset < len(self.buf) and now_stream:
            cur -= 1
            log_dbg(f"cur: {cur}, offset: {self.offset}")

            for now_stream in self.parser_buf(now_stream):
                if not now_stream:
                    break

                if 'json[0]["request"]' in self.stream_map:
                    request = self.stream_map['json[0]["request"]']
                    log_dbg(
                        f"self.path: {self.path} req path: {request.path} req done {request.done}"
                    )

                if self.offset >= len(self.buf):
                    break

                log_dbg(
                    f"now_path: {self.path}, type: {now_stream.type}, buf: {self.buf[self.offset:]}"
                )

                if now_stream.done:
                    break

            log_dbg(
                f"({self.path}) ({now_stream.path}) {now_stream.type} now_stream: {now_stream}"
            )

            if now_stream:
                if now_stream.path == JsonStreamRoot.Root:  # root
                    self.done = now_stream.done

                if (
                    now_stream.type != JsonStreamDataType.OBJ
                    and now_stream.type != JsonStreamDataType.ARR
                    and now_stream.type != JsonStreamDataType.UND
                ):
                    yield now_stream

                if now_stream.done:
                    if (
                        now_stream.type == JsonStreamDataType.ARR
                        or now_stream.type == JsonStreamDataType.OBJ
                    ):
                        yield now_stream

                    self.parser_stream_done(now_stream)

            now_stream = self.stream_map[self.path]
            log_dbg(f"exit. cur: {cur} now_stream: {now_stream}")

    def get_next_parser_path(self, stream: JsonStreamData):
        if not stream.done:
            return stream.path
        if JsonStreamRoot.Root == stream.path:
            return JsonStreamRoot.Root

        return self.get_next_parser_path(stream.parent)

    def parser_stream_done(self, stream: JsonStreamData):
        log_dbg(f"check done type: {stream.type}, data: {str(stream.data)}")
        if not stream.done:
            return stream

        log_dbg(
            f"path: {self.path}, type: {stream.type}, "
            f"offset: {self.offset}, all: {len(self.buf)}, stream done. "
        )

        if stream.parent.type == JsonStreamDataType.OBJ:
            stream.parent.type_parser_reset()

        next_parser_path = self.get_next_parser_path(stream)
        log_dbg(f"update path {self.path} to {next_parser_path}")
        self.path = next_parser_path

        stream.type_parser_reset()

        # root json
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

        log_dbg(f"({self.path}) parser: {buf[offset]}, type: {type}")

        return type

    def parser_buf(self, stream: JsonStreamData):
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
            yield from hook(stream)
        else:
            yield from self.parser_und(stream)

    def parser_und(self, stream: JsonStreamData):
        if stream.type == JsonStreamDataType.UND:
            # 未定义场景, 表示还没开始处理数据. 所以现在进行尝试.
            while self.offset < len(self.buf) and (
                self.need_skip_char(self.buf[self.offset])
            ):
                self.offset += 1

            if self.offset < len(self.buf):
                type = self.get_parser_type(self.buf, self.offset)
                log_dbg(f"({self.path}) check {stream.type} {stream} get type: {type}")
                if type not in JsonStreamDataType.ALL:
                    log_dbg(
                        f"cannot parser , type: {str(type)}, "
                        f"offset: {self.offset}, all: {len(self.buf)} buf: {self.buf[self.offset:]}"
                    )
                else:
                    stream.reset(type)
                    log_dbg(f"({self.path}) new stream type: {stream.type} {stream}")

                    if type == JsonStreamDataType.ARR:
                        self.offset += 1  # 跳过生成过的字符.
                    elif type == JsonStreamDataType.OBJ:
                        self.offset += 1  # 跳过生成过的字符.
                    elif type == JsonStreamDataType.STR:
                        self.offset += 1  # 跳过生成过的字符.
                    else:
                        pass

                    yield from self.parser_buf(stream)

        yield stream

    def append_stream(self, path, stream) -> JsonStreamData:
        if path not in self.stream_map:
            self.stream_map[path] = stream
        return self.stream_map[path]

    def get_stream(self, path) -> JsonStreamData:
        if path not in self.stream_map:
            stream = JsonStreamData(JsonStreamDataType.UND, path)
            self.stream_map[path] = stream

        return self.stream_map[path]

    def get_now_parser_obj_stream(self, obj_stream: JsonStreamData):
        if obj_stream.now_key in obj_stream.stream_data:
            return obj_stream.stream_data[obj_stream.now_key]

        new_path = f'{self.path}["{obj_stream.now_key}"]'
        stream = self.get_stream(new_path)
        stream.parent = obj_stream
        obj_stream.stream_data[obj_stream.now_key] = stream

        self.path = new_path

        return stream

    def parser_obj(self, obj_stream: JsonStreamData):
        if obj_stream.type == JsonStreamDataType.OBJ:
            cur = len(self.buf) - self.offset
            while cur and self.offset < len(self.buf):
                cur -= 1

                log_dbg(
                    f"try parser: {self.buf[self.offset]}, now_offset: {self.offset}, all: {len(self.buf)}"
                )

                if not obj_stream.key_start:
                    # 还没解析 key 就到了尾声, 如果结束了的话, 就设置完成.
                    if self.buf[self.offset] == "}" and self.is_real_ch(
                        self.buf, self.offset
                    ):
                        obj_stream.done = True
                        self.offset += 1
                        log_dbg(
                            f"self.path: {self.path}, obj_stream.path: {obj_stream.path}, "
                            f"obj_stream done. {obj_stream}"
                        )
                        break

                    if self.buf[self.offset] == ",":
                        self.offset += 1
                        continue

                    if self.buf[self.offset] == '"':
                        obj_stream.key_start = self.offset + 1
                        log_dbg(f"start: {obj_stream.key_start}")
                    self.offset += 1
                    continue

                if not obj_stream.key_end:
                    if self.buf[self.offset] == '"' and self.is_real_ch(
                        self.buf, self.offset
                    ):
                        obj_stream.key_end = self.offset
                        log_dbg(f"end: {obj_stream.key_end}")
                    self.offset += 1
                    continue

                obj_stream.now_key = self.buf[obj_stream.key_start : obj_stream.key_end]

                stream = self.get_now_parser_obj_stream(obj_stream)

                if not obj_stream.colon_offset:
                    if self.buf[self.offset] == ":":
                        obj_stream.colon_offset = self.offset
                    self.offset += 1
                    continue

                if self.need_skip_char(self.buf[self.offset]):
                    self.offset += 1
                    continue

                log_dbg(
                    f"({self.path}) ({obj_stream.path}) {obj_stream.type} obj_stream[{obj_stream.now_key}] = {self.buf[self.offset:]}...?"
                )
                log_dbg(f"self.offset: {self.offset}, buf_len: {len(self.buf)}, ")

                for sub_stream in self.parser_buf(stream):
                    sub_stream: JsonStreamData

                    if not sub_stream:
                        continue

                    if sub_stream.parent != obj_stream:
                        yield sub_stream
                        break

                    log_dbg(
                        f"send type: {sub_stream.type}, data: {str(sub_stream.data)}, done: {str(sub_stream.done)}"
                    )

                    yield sub_stream

                    if sub_stream.done:
                        break

        yield obj_stream

    def get_now_parser_arr_stream(self, arr_stream: JsonStreamData) -> JsonStreamData:
        now_path = f"{self.path}[{arr_stream.now_arr_cnt}]"
        stream = self.get_stream(now_path)
        arr_data: List[JsonStreamData] = arr_stream.stream_data

        if len(arr_data) < arr_stream.now_arr_cnt + 1:
            stream.parent = arr_stream
            self.path = now_path
            arr_data.append(stream)

        return stream

    def parser_arr(self, arr_stream: JsonStreamData):
        if arr_stream.type == JsonStreamDataType.ARR:
            cur = len(self.buf) - self.offset

            now_stream = self.get_now_parser_arr_stream(arr_stream)

            while cur and self.offset < len(self.buf):
                cur -= 1

                log_dbg(f"cur: {cur}, offset: {self.offset}, all: {len(self.buf)}")

                if self.need_skip_char(self.buf[self.offset]):
                    self.offset += 1
                    continue

                # 还没开始拿到元素就结束数组了
                if self.buf[self.offset] == "]":
                    arr_stream.done = True
                    self.offset += 1
                    log_dbg(
                        f"self.path: {self.path}, arr_dream.path: {arr_stream.path}, "
                        f"arr_strem done. {arr_stream}"
                    )
                    break

                # 出现新下标就创建新的继续解析
                if self.buf[self.offset] == ",":
                    arr_stream.now_arr_cnt += 1
                    self.offset += 1
                    now_stream = self.get_now_parser_arr_stream(arr_stream)

                    continue

                for item_stream in self.parser_buf(now_stream):
                    item_stream: JsonStreamData

                    if not item_stream:
                        continue

                    if item_stream.parent != arr_stream:
                        yield item_stream
                        break

                    log_dbg(
                        f"({self.path}): item type: {item_stream.type}, ({item_stream.path}) item_data: {item_stream.str()}"
                    )

                    yield item_stream

                    if item_stream.done:
                        break

        yield arr_stream

    def parser_num(self, num_stream: JsonStreamData):
        if num_stream.type == JsonStreamDataType.NUM:
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
                    num_stream.set_data(int(num))

                    num_stream.chunk = num_stream.data
                    num_stream.done = True

                    break

                self.offset += 1

        yield num_stream

    def parser_nul(self, nul_stream: JsonStreamData):
        if nul_stream.type == JsonStreamDataType.NUL:
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
                    nul_stream.set_data(None)

                    nul_stream.chunk = nul_stream.data

                    nul_stream.done = True

                    break

                self.offset += 1

        yield nul_stream

    def parser_bol(self, bol_stream: JsonStreamData):
        if bol_stream.type == JsonStreamDataType.BOL:
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
                        bol_stream.set_data(True)
                    else:
                        bol_stream.set_data(False)
                    bol_stream.chunk = bol_stream.data
                    bol_stream.done = True

                    break

                self.offset += 1

        yield bol_stream

    def parser_str(self, str_stream: JsonStreamData):
        if str_stream.type == JsonStreamDataType.STR:
            cur = len(self.buf) - self.offset

            str_stream.chunk = ""

            while cur and self.offset < len(self.buf):
                cur -= 1

                log_dbg(
                    f"({self.path}) ({str_stream.path}) {str_stream.type} parser str. "
                    f"offset: {self.offset}, val: {self.buf[self.offset:]}"
                )

                if self.buf[self.offset] == '"' and (
                    self.is_real_ch(self.buf, self.offset)
                ):
                    self.offset += 1
                    str_stream.done = True
                    log_dbg(
                        f"({self.path}) ({str_stream.path}) {str_stream.type} stream parser done: {str_stream.data}"
                    )
                    break

                real_ch = self.buf[self.offset]

                if "\\" == real_ch and self.is_real_ch(self.buf, self.offset):
                    print(f"skip escape ch: {real_ch}")
                    self.offset += 1
                    continue

                if not self.is_real_ch(self.buf, self.offset):
                    escape = {
                        "\\": "\\",
                        '"': '"',
                        "/": "/",
                        "b": "\b",
                        "f": "\f",
                        "n": "\n",
                        "r": "\r",
                        "t": "\t",
                    }
                    real_ch = escape.get(real_ch)
                    if not real_ch:
                        real_ch = self.buf[self.offset]
                    else:
                        print(f"pack real_ch to [{real_ch}]")

                new_data = str_stream.stream_data + real_ch
                str_stream.set_data(new_data)

                str_stream.chunk += real_ch

                self.offset += 1

        yield str_stream

    def is_real_ch(self, buf, now_offset):
        now = buf[now_offset]
        log_dbg(f"check end: {now}")

        if now_offset < 1:  # 至少要有两个字符
            return False

        if buf[now_offset - 1] != "\\":  # 前面不是 \ , 这里收到了 " 说明 json val 结束
            return True
        if now_offset < 2:
            return True

        if buf[now_offset - 2] != "\\":  # ?\" continue
            return False
        if now_offset < 3:
            return False

        if buf[now_offset - 3] != "\\":  # ? \\ " end
            return True
        if now_offset < 4:
            return True

        if buf[now_offset - 4] != "\\":  # ? \\ \" continue
            return False

        # \\ \\ " end
        return True


if __name__ == "__main__":
    # ```json
    rsp_data_0 = """
[
    {
        "type": "object", 
        "timestamp": 4, 
        "expect": "hello", 
        "reasoning": "In order to reply to a message, you need to briefly think about where to start.  ", 
        "call": "chat_to_master", 
        "request": {
            "type": "object",
            "content": "[AimiCore] Hello, I have initialized. ", 
            "from": [
                2
            ]
        }, 
        "conclusion": "To comply with the Guidance, I replied 'hello'.", 
        "execute": "system"
    },
    """
    rsp_data_1 = """ 
    {
        "type": "object",
        "timestamp": 5,
        "expect": "Return a greeting",
        "reasoning": "AimiCore began to think: The Master said good evening to me, and I needed to respond to the greeting. ",
        "call": "chat_to_master",
        "request": {
            "type": "object",
            "content": 
"""
    rsp_data_2 = '"['
    rsp_data_3 = """AimiCore] Good evening, Master! What can I do for you?",
            "from": [
                2
            ]
        },
        "conclusion": "According to the Guidance, I responded to the Master's greeting and asked if I could help. ",
        "execute": "system"
    },
    """
    rsp_data_4 = """
{"type": "object", "timestamp": 28, "expect": "Questions and Answers", "reasoning": "AimiCore started thinking: The Master wanted to know how to display the running time in the process of running the program using the subprocess call, and needed to be in milliseconds. I should answer his question." , "call": "chat_to_master", "request": {"type": "object", "content":  "To display a running time when you run a program using a subprocess call, you can get a timestamp at the start and end of the program and calculate the time difference. You can use the time module's time() function to get a timestamp in seconds and multiply it by 1,000 to convert it to milliseconds. The following code is an example: \\n\\n```python\\nimport subprocess\\nimport time\\n\\nstart_time = int(time.time() *  1000)\\nsubprocess.run(['your_program'])\\nend_time = int(time.time() * 1000)\\n\\nelapsed_time = end_time -  start_time\\nprint(' elapsed time of the program in milliseconds: ', elapsed_time)\\n ```\\n\\n This will display the elapsed time in milliseconds when the program is run.", "from": [0]}, "conclusion": "According to the Master's problem, this paper gives the solution of how to display the running time when using the subprocess call to run the program.", "execute": "system"}]
    """
    rsp_data_arr = [rsp_data_0, rsp_data_1, rsp_data_2, rsp_data_3, rsp_data_4]
    # ```

    # You can access keys(type -> json[0]["type"]) like this:
    # ```python
    # jss = JsonStream()
    # for s in rsp_data: # s is stream str
    #     for stream in jss.parser(s):
    #         if stream.path == 'json[0]["type"]':
    #             print(f"json type: {stream.data}")
    #             if stream.done:
    #                 print(f"stream type parser done.")
    # ```
    #
    # output:
    # ```bash
    # json type: object
    # stream type parser done.
    # ````
    # # The meaning of `path`

    # json: json is an array structure or object structure

    # Where [num] (num is a number) indicates that the data is an array
    # json[0]: Access the first element of the array
    # json[0][0]: The first element of an array is an array

    # Where ["Test"] (Key is enclosed in double quotes) means that the key of object is accessed as a member of Test,
    # json["Test"]: Access a value in object whose key is Test

    # It can also be combined:
    # json[0]["Test"]: Access the first element of the array, and then access the value of the element whose Key is Test

    json_stream = JsonStream()

    for it in rsp_data_arr:
        for stream in json_stream.parser(it):
            data = json_stream.path_data
            print(f"type: {stream.type} chunk: {stream.chunk} ")
            if stream.path == 'json[2]["request"]' and stream.done:
                print(f"req: {stream.data}")
            l = len(json_stream.data)
            print(f"jss len: {l}")
            continue

    root = json_stream.get_stream(JsonStreamRoot.Root)
    request = json_stream.get_stream('json[2]["request"]')

    print(
        f"output({json_stream.done}) type:{root.type}:\n```json\n{json_stream.data}\n```\n"
    )

    import json

    js = json.dumps(root.data, indent=4, ensure_ascii=False)
    print(f"root:\n```json\n{js}\n```\n")
    print(f"j[2]req:\n{request.data}")

    # for k, v in json_stream.stream_map.items():
    #     print(f"jss. type: {v.type} k: {k} v: {v.str()} stream: {v}")

    # root = json_stream.stream_map['json.arr[0]']
    # print(f"jss: {root.str()}")
