import json5
import json
import os
import re
from typing import Dict, Any, List, Generator, Optional, Union, Set
from pydantic import BaseModel, constr

from tool.config import Config
from tool.util import (
    log_dbg,
    log_err,
    log_info,
    make_context_messages,
    write_yaml,
    load_module,
    green_input,
    move_key_to_first_position,
    is_json,
)

from tool.json_stream import JsonStream, JsonStreamData, JsonStreamRoot

from core.aimi_plugin import (
    ChatBot,
    ChatBotType,
    ActionToolItem,
    ExternAction,
    BotAskData,
    Bot,
)
from core.sandbox import Sandbox, RunCodeReturn


class TaskStepItem(BaseModel):
    type: str = "object"
    from_task_id: Optional[Union[int, str, None]] = None
    step_id: Optional[Union[int, str]]
    step: Optional[Union[int, str]]
    check: Optional[Union[str, None]] = ""
    call: Optional[Union[str, None]] = None
    call_timestamp: Optional[
        Union[List[str], List[int], List[None], str, int, None]
    ] = []


class TaskRunningItem(BaseModel):
    type: str = "object"
    timestamp: int
    expect: Optional[Union[str, None]] = None
    reasoning: Optional[Union[str, None]] = None
    call: str
    request: Any
    conclusion: Optional[Union[str, None]] = None
    execute: constr(regex="system|AI")


class TaskActionKey:
    Type = "type"
    Timestamp = "timestamp"
    Expect = "expect"
    Reasoning = "reasoning"
    Call = "call"
    Request = "request"
    Conclusion = "conclusion"
    Execute = "execute"


class TaskActionRequestKey:
    Content = "content"


class TaskRunningItemStreamType:
    Type = f'{JsonStreamRoot.Root}[0]["{TaskActionKey.Type}"]'
    Timestamp = f'{JsonStreamRoot.Root}[0]["{TaskActionKey.Timestamp}"]'
    Expect = f'{JsonStreamRoot.Root}[0]["{TaskActionKey.Expect}"]'
    Reasoning = f'{JsonStreamRoot.Root}[0]["{TaskActionKey.Reasoning}"]'
    Call = f'{JsonStreamRoot.Root}[0]["{TaskActionKey.Call}"]'
    Request = f'{JsonStreamRoot.Root}[0]["{TaskActionKey.Request}"]'
    Conclusion = f'{JsonStreamRoot.Root}[0]["{TaskActionKey.Conclusion}"]'
    Execute = f'{JsonStreamRoot.Root}[0]["{TaskActionKey.Execute}"]'

    def __init__(self, root_idx=0):
        self.Type = f'{JsonStreamRoot.Root}[{root_idx}]["{TaskActionKey.Type}"]'
        self.Timestamp = (
            f'{JsonStreamRoot.Root}[{root_idx}]["{TaskActionKey.Timestamp}"]'
        )
        self.Expect = f'{JsonStreamRoot.Root}[{root_idx}]["{TaskActionKey.Expect}"]'
        self.Reasoning = (
            f'{JsonStreamRoot.Root}[{root_idx}]["{TaskActionKey.Reasoning}"]'
        )
        self.Call = f'{JsonStreamRoot.Root}[{root_idx}]["{TaskActionKey.Call}"]'
        self.Request = f'{JsonStreamRoot.Root}[{root_idx}]["{TaskActionKey.Request}"]'
        self.Conclusion = (
            f'{JsonStreamRoot.Root}[{root_idx}]["{TaskActionKey.Conclusion}"]'
        )
        self.Execute = f'{JsonStreamRoot.Root}[{root_idx}]["{TaskActionKey.Execute}"]'


class TaskRunItemStreamReqType(TaskRunningItemStreamType):
    Content = f'{JsonStreamRoot.Root}[0]["{TaskActionKey.Request}"]["{TaskActionRequestKey.Content}"]'

    def __init__(self, root_idx=0):
        super().__init__(root_idx)
        self.Content = f'{JsonStreamRoot.Root}[{root_idx}]["{TaskActionKey.Request}"]["{TaskActionRequestKey.Content}"]'


class TaskStreamContext:
    jss: JsonStream
    check: Dict = {}
    data: List[TaskRunningItem] = []
    listen_calls: List[str]
    error: str = ""

    def need_wait(self) -> bool:
        if len(self.error):
            return False
        # 没有解析到动作的时候进行等待
        if not len(self.data[0].call):
            return True
        if self.action_start():
            return True
        return False

    def clear_cache(self):
        self.check = {}
        self.jss = JsonStream()
        task = TaskRunningItem(timestamp=0, call="", request=None, execute="system")
        self.data = [task]

    def get_task_stream(self) -> TaskRunningItem:
        return self.data[0]

    def get_action_key_by_stream_key(self, stream_type: TaskRunningItemStreamType):
        map_list = {
            TaskRunningItemStreamType.Type: TaskActionKey.Type,
            TaskRunningItemStreamType.Timestamp: TaskActionKey.Timestamp,
            TaskRunningItemStreamType.Reasoning: TaskActionKey.Reasoning,
            TaskRunningItemStreamType.Expect: TaskActionKey.Expect,
            TaskRunningItemStreamType.Call: TaskActionKey.Call,
            TaskRunningItemStreamType.Request: TaskActionKey.Request,
            TaskRunningItemStreamType.Execute: TaskActionKey.Execute,
            TaskRunningItemStreamType.Conclusion: TaskActionKey.Conclusion,
        }
        return map_list.get(stream_type)

    def action_start(self) -> bool:
        # 不能处理 timestamp 为 0 的情况
        if 0 == self.data[0].timestamp:
            return False

        # 如果第一个不是 要处理的, 那么就不管
        if self.data[0].call in self.listen_calls:
            return True
        return False

    def is_first(self) -> bool:
        if self.jss.path not in self.check:
            return True
        return False

    @property
    def done(self):
        if self.data[0].call not in self.listen_calls:
            return False

        return self.jss.done

    def parser(self, buf) -> Generator[JsonStreamData, None, None]:
        for stream in self.jss.parser(buf):
            try:
                if stream.done:
                    action_key = self.get_action_key_by_stream_key(stream.path)
                    log_dbg(f"{stream.path} = {stream.data}")

                    if stream.path == TaskRunningItemStreamType.Call:
                        if stream.data not in self.listen_calls:
                            self.error = f"not support stream call: {stream.data}"
                            raise Exception(self.error)

                    if action_key and hasattr(self.data[0], action_key):
                        setattr(self.data[0], action_key, stream.data)

                yield stream

                self.check[self.jss.path] = stream.done
            except Exception as e:
                log_dbg(f"fail to parser date: {e}")
                raise Exception(f"fail to parser steam: {e}")

    def __init__(self, listen_calls: List[str]):
        self.listen_calls = listen_calls
        self.clear_cache()


class TaskItem(BaseModel):
    type: str = "object"
    task_id: Optional[Union[int, str]]
    task_info: str
    now_task_step_id: Optional[Union[int, str]] = ""
    task_step: List[TaskStepItem] = []


class Task(Bot):
    type: str = "task"
    tasks: Dict[int, TaskItem] = {}
    action_tools: List[ActionToolItem] = []
    extern_action: ExternAction
    notes: List[str] = []
    keep_note_len: int = 0
    execute_system_calls: List[str] = []
    execute_ai_calls: List[str] = []
    now_task_id: str = 1
    aimi_name: str = "Aimi"
    master_name: str = "Master"
    running: List[TaskRunningItem] = []
    max_running_size: int = 5 * 1000
    max_note_size: int = 15
    timestamp: int = 1
    chatbot: ChatBot
    task_has_change: bool = True
    run_model = Sandbox.RunModel.system
    run_timeout: int = 15
    use_talk_messages: bool = True
    models: List[str] = []
    now_ctx_size: int = 0

    def task_dispatch_stream(
        self, tsc: TaskStreamContext, res: str
    ) -> Generator[str, None, None]:
        try:
            for stream in tsc.parser(res):
                if stream.path == TaskRunningItemStreamType.Type:
                    if stream.done:
                        log_dbg(f"Type: {stream.data}")
                elif stream.path == TaskRunningItemStreamType.Timestamp:
                    if stream.done:
                        timestamp = int(stream.data)
                        log_dbg(f"Timestamp: {timestamp}")
                        if timestamp < int(self.timestamp):
                            raise Exception(
                                f"system error: AI try copy old action, time: {timestamp}"
                            )
                elif stream.path == TaskRunningItemStreamType.Expect:
                    if tsc.is_first():
                        yield f"**Expect**: "
                    yield stream.chunk
                    if stream.done:
                        log_dbg(f"Expect: {stream.data}")
                        yield "\n"
                elif stream.path == TaskRunningItemStreamType.Reasoning:
                    if tsc.is_first():
                        yield f"**Reasoning**: "
                    yield stream.chunk
                    if stream.done:
                        log_dbg(f"Reasoning: {stream.data}")
                        yield "\n\n"
                elif stream.path == TaskRunningItemStreamType.Call:
                    if stream.done:
                        log_dbg(f"Call: {stream.data}")
                elif TaskRunningItemStreamType.Request in stream.path:
                    task_stream = tsc.get_task_stream()
                    if (
                        task_stream.call.lower()
                        == f"chat_to_{self.master_name.lower()}"
                    ):
                        if stream.path == TaskRunItemStreamReqType.Content:
                            if tsc.is_first():
                                yield f"**To {self.master_name}**: \n"
                            yield stream.chunk
                            if stream.done:
                                log_dbg(
                                    f"To {self.master_name}: {stream.path} {stream.data}"
                                )
                                yield "\n"

                elif stream.path == TaskRunningItemStreamType.Conclusion:
                    if tsc.is_first():
                        yield f"\n**Conclusion**: "
                    yield stream.chunk
                    if stream.done:
                        log_dbg(f"Conclusion: {stream.data}")
                        yield "\n"

            if tsc.done:
                try:
                    task = tsc.get_task_stream()
                    self.__append_running([task])

                    log_dbg(f"update running success: {len(str(task))}")
                except Exception as e:
                    raise Exception(f"fail to append running: {str(e)}")

        except Exception as e:
            tsc.error = f"cann't parser stream: {e}"
            log_dbg(tsc.error)
            raise Exception(tsc.error)

    def running_append_task(
        self, running: List[TaskRunningItem], task: TaskRunningItem
    ):
        if not task:
            log_dbg(f"task len overload: {len(str(task))}")
            return running

        new_running = []

        task.timestamp = int(self.timestamp)
        self.timestamp += 1
        new_running.append(task)

        for run in reversed(running):
            if (len(str(new_running)) + len(str(run))) > self.max_running_size:
                break
            new_running.insert(0, run)

        return new_running

    def task_dispatch(self, res: str) -> Generator[str, None, None]:
        def get_json_content(answer: str):
            has_error = False
            # del ```python
            start_index = answer.find("```json\n[")
            if start_index != -1:
                log_err(f"AI add ```python format")
                has_error = True

                start_index += 8
                end_index = answer.rfind("]\n```", start_index)
                if end_index != -1:
                    answer = answer[start_index : end_index + 1]

            if "{" == answer[0] and "}" == answer[-1]:
                log_err(f"AI no use format, try add List []")
                has_error = True
                return f"[{answer}]", has_error

            # search List `[` and `]`
            if start_index == -1:
                start_index = answer.find("[")
                if start_index != -1:
                    end_index = answer.rfind("]", start_index)
                    if end_index != -1:
                        if "]" == answer[-1]:
                            # 防止越界
                            answer = answer[start_index:]
                        else:
                            answer = answer[start_index : end_index + 1]
                        # 去除莫名其妙的解释说明

            if '[{\\"type\\":' in answer:
                log_err(f'AI no use js format, has \\" ')
                has_error = True
                answer = answer.replace('\\"', '"')

            return answer, has_error

        def repair_action_dict(data):
            has_error = False
            if "action" in data and "{" in data and len(data) == 1:
                log_err(f"data fail, try set action out Dict: {str(data)}")
                has_error = True
                return data["action"], has_error

            all_action_tools = self.action_tools
            all_action_tools.extend(self.extern_action.brief())

            for action in data:
                # set action -> call
                try:
                    if "action" in action and "call" not in action:
                        _action = action["action"]
                        log_err(f"AI not set call, try fill action: {_action}")
                        action["call"] = str(action["action"])
                        del action["action"]
                        has_error = True
                except Exception as e:
                    raise Exception(f"fail to pair action call: {str(e)}")

                try:

                    # set action -> request
                    if "action" in action and "request" not in action:
                        _request = action["action"]
                        log_err(f"AI not set request, try fill action: {_request}")
                        action["request"] = action["action"]
                        del action["action"]
                        has_error = True

                except Exception as e:
                    raise Exception(f"fail to set action -> request: {str(e)}")

                try:
                    # set chat_from execute -> system
                    if "chat_from_" in action["call"] and "execute" not in action:
                        _call = action["call"]
                        log_err(f"AI try call: chat_from_: {_call}")
                        action["execute"] = "system"
                        has_error = True
                except Exception as e:
                    raise Exception(
                        f"fail to fill chat_from excute -> system: {str(e)}"
                    )

                for tool in all_action_tools:
                    try:
                        if action["call"] != tool.call:
                            continue
                        # fix no execute.
                        if "execute" in action and action["execute"] != tool.execute:
                            log_err(f"AI try overwrite execute: {tool.call}")
                            action["execute"] = tool.execute
                            has_error = True
                        if "execute" not in action:
                            log_dbg(
                                f"fill call({tool.call}) miss execute: {tool.execute}"
                            )
                            action["execute"] = tool.execute

                    except Exception as e:
                        raise Exception(f"fail to fix excute of {tool.call}: {str(e)}")

                    try:
                        if (
                            "dream" != action["call"]
                            and "request" in action
                            and isinstance(action["request"], dict)
                            and "type" not in action["request"]
                        ):
                            log_err(f"AI no set object type: {tool.call}")
                            action["request"]["type"] = "object"
                            has_error = True

                    except Exception as e:
                        raise Exception(f"fail to fill action object type: {str(e)}")

            return data, has_error

        log_dbg(f"timestamp: {str(self.timestamp)}")
        log_dbg(f"now_ctx_size: {str(self.now_ctx_size)}")
        log_dbg(f"now task: {str(self.tasks[int(self.now_task_id)].task_info)}")

        response = ""
        has_error = False
        has_format_error = False
        running: List[TaskRunningItem] = []
        try:
            answer, has_format_error = get_json_content(res)

            # 忽略错误.
            # decoder = json.JSONDecoder(strict=False)
            # data = decoder.decode(answer)
            data = {}
            try:
                # del zh ,  ..
                answer = answer.replace(", ", ", ")
                data = json5.loads(answer)
            except Exception as e:
                raise Exception(f"fail to load data: {str(e)}")

            try:
                data, has_format_error = repair_action_dict(data)
            except Exception as e:
                raise Exception(f"fail to repair_action_dict: {str(e)}")

            tasks = []
            try:
                tasks = [TaskRunningItem(**item) for item in data]
            except Exception as e:
                raise Exception(f"fail to trans task Base: {str(e)}")

            system_call_cnt = 0
            skip_call = 0
            skip_timestamp = 0
            task_cnt = 1
            for task in tasks:
                try:
                    log_dbg(
                        f"[{task_cnt}] get task: {str(task.call)} : {str(task)}\n\n"
                    )

                    task_cnt += 1
                    task_response = ""

                    if int(task.timestamp) < int(self.timestamp):
                        skip_timestamp += 1
                        log_err(
                            f"[{str(skip_timestamp)}] system error: AI try copy old action call: {task.call}"
                        )
                        has_error = True
                        continue

                    if "chat_from_" in task.call:
                        if task.call.lower() == f"chat_from_{self.master_name.lower()}":
                            log_err(
                                f"{str(task.call)}: AI try predict {self.master_name.lower()}: {str(task.request)}"
                            )
                            has_error = True
                        else:
                            log_err(f"{str(task.call)}: AI create char_from.")
                            has_error = True
                        continue

                    if task.call in self.execute_system_calls or has_error:
                        system_call_cnt += 1

                    if system_call_cnt > 1:
                        skip_call += 1
                        log_err(
                            f"[{str(skip_call)}] system error: AI try predict system call: {task.call}"
                        )
                        has_error = True
                        continue

                    if task.expect:
                        log_dbg(f"{str(task.call)} expect: {str(task.expect)}")
                        yield f"**Expect:** {task.expect}\n"

                    if task.reasoning:
                        log_dbg(f"{str(task.call)} reasoning: {str(task.reasoning)}")
                        yield f"**Reasoning:** {task.reasoning}\n\n"

                    if task.request and "from" in task.request:
                        from_timestamp = str(task.request["from"])
                        log_dbg(f"from_timestamp: {from_timestamp}")

                    if task.call.lower() == f"chat_to_{self.master_name.lower()}":
                        content = str(task.request["content"])
                        log_dbg(f"{self.aimi_name}: {content}")
                        yield f"**To {self.master_name}:** \n{content}\n"

                    elif task.call == "set_task_info":
                        task_id: int = int(task.request["task_id"])
                        task_info: str = task.request["task_info"]
                        now_task_step_id: int = self.tasks[
                            self.now_task_id
                        ].now_task_step_id
                        if "now_task_step_id" in task.request:
                            now_task_step_id = int(task.request["now_task_step_id"])
                        self.set_task_info(task_id, task_info, now_task_step_id)
                        yield f"**Set task info:** {task_info}\n"

                    elif task.call == "set_task_step":
                        task_id: str = task.request["task_id"]
                        now_task_step_id: str = task.request["now_task_step_id"]
                        request_task_step = task.request["task_step"]
                        task_step = []
                        try:
                            task_step = [
                                TaskStepItem(**step) for step in request_task_step
                            ]
                        except Exception as e:
                            log_err(
                                f"fail to load task_step: {str(e)}: {str(request_task_step)}"
                            )
                            has_error = True
                            continue
                        yield from self.set_task_step(
                            task_id, now_task_step_id, task_step
                        )

                    elif task.call == "critic":
                        yield from self.critic(task.request)

                    elif task.call == "analysis":
                        yield "**Think...**\n"

                        yield from self.analysis(task.request)

                    elif task.call == "suppose":
                        yield "**Comprehend...**\n"

                        yield from self.suppose(task.request)

                    elif task.call == "dream":
                        dream = self.dream(task.request)
                        yield f"**Woolgather:** \n```javascript\n{dream}\n```\n"

                    elif task.call == "chat_to_append_note":
                        note = task.request["note"]
                        response = self.chat_to_append_node(note)
                        task_response = self.make_chat_from(
                            from_timestamp=self.timestamp,
                            from_name="append_note",
                            content=response,
                            request_description="`response->append_note` 的内容是 系统 append_note 返回内容.",
                        )
                        yield f"**Note:** {note}\n"

                    elif task.call == "chat_to_wolfram":
                        math = task.request["math"]
                        response = self.chat_to_wolfram(task.request["math"])
                        yield f"**Calculate:** $$ {math} $$\n"
                        task_response = self.make_chat_from(
                            from_timestamp=self.timestamp,
                            from_name="wolfram",
                            content=response,
                            request_description="`response->wolfram` 的内容是 云端 wolfram 返回内容.",
                        )
                        yield f"**Computation:** \n```javascript\n{response}\n```\n"

                    elif task.call == "chat_to_gemini":
                        ask_gemini = task.request["content"]
                        yield f"**Ask Gemini:** \n{ask_gemini}\n"

                        yield f"**Gemini reply:** \n"
                        response = ""
                        for res in self.chat_to_gemini(ask_gemini):
                            response = res
                            yield response

                        task_response = self.make_chat_from(
                            from_timestamp=self.timestamp,
                            from_name="gemini",
                            content=response,
                            request_description="`response->gemini` 的内容是 gemini 回复的话.",
                        )

                    elif task.call == "chat_to_bing":
                        ask_bing = task.request["content"]
                        yield f"**Ask Bing:** \n{ask_bing}\n"

                        yield f"**Bing reply:** \n"
                        response = ""
                        for res in self.chat_to_bing(ask_bing):
                            response = res
                            yield response

                        task_response = self.make_chat_from(
                            from_timestamp=self.timestamp,
                            from_name="bing",
                            content=response,
                            request_description="`response->bing` 的内容是 bing 回复的话.",
                        )
                        yield f"\n"

                    elif task.call == "chat_to_python":
                        python_code = task.request["code"]
                        if (
                            len(python_code) > 9
                            and "```python" == python_code[:9]
                            and "```" == python_code[-3:]
                        ):
                            python_code = python_code[10:-4]
                            log_dbg(f"del code cover: ```python ...")

                        log_info(f"\n```python\n{python_code}\n```")
                        yield f"**Programming:** \n```python\n{python_code}\n```\n"

                        success, response = self.chat_to_python(
                            self.timestamp, python_code
                        )

                        task_response = self.make_chat_from(
                            from_timestamp=self.timestamp,
                            from_name="python",
                            content=response,
                            request_description="`response->python` 的内容是 python运行信息.",
                        )

                        stdout = response["stdout"]
                        runtime = response["runtime"]
                        if success:
                            yield f"**Execution result[{runtime}s]:** \n```javascript\n{stdout}\n```\n"
                        else:
                            yield f"**Execution failed[{runtime}s]:** \n```javascript\n{stdout}\n```\n"

                    elif task.call == "chat_to_chatgpt":
                        aimi = task.request[f"{self.aimi_name}"]
                        chatgpt = ""
                        try:
                            chatgpt = task.request["chatgpt"]
                        except Exception as e:
                            log_err(f"AI no set chatgpt response.")
                            has_error = True

                        log_info(f"{self.aimi_name}: {aimi}\nchatgpt:{chatgpt}")
                        yield "**Think to oneself:**\n"
                        yield f"**Ask oneself:** \n{aimi}\n"
                        yield f"**Answer self:** \n{chatgpt}\n"

                    elif task.call == "chat_to_save_action":
                        save_action_call = ""
                        if "save_action_call" in task.request:
                            save_action_call = task.request["save_action_call"]

                        save_action = None
                        save_description = "..."
                        if "save_action" in task.request:
                            save_action = task.request["save_action"]
                        if "description" in save_action:
                            save_description = save_action["description"]

                        save_action_code = None
                        if "save_action_code" in task.request:
                            save_action_code = task.request["save_action_code"]
                            if save_action_code and (
                                "None" == save_action_code or "null" == save_action_code
                            ):
                                save_action_code = None

                        yield "**Self iteration...**\n"
                        done, response = self.chat_to_save_action(
                            save_action_call, save_action, save_action_code
                        )
                        task_response = self.make_chat_from(
                            from_timestamp=self.timestamp,
                            from_name="save_action",
                            content=response,
                            request_description=f"`response->save_action` "
                            f"的内容是 {task.call} 运行信息.",
                        )
                        if done:
                            yield f"**New ability:** * {save_description} *\n"

                            if save_action_code:
                                yield f"**Ability method:** \n```python\n{save_action_code}\n```\n"

                    elif task.call in self.extern_action.actions:
                        try:
                            action_call = self.extern_action.actions[task.call]
                            chat_from = action_call.chat_from
                            action_description = action_call.action.description

                            yield f"**Ability to try:** * {action_description} *\n"

                            req = task.request if task.request else ""
                            req_format = json.dumps(req, indent=4, ensure_ascii=False)

                            if (
                                "null" != req_format
                                and len(req)
                                and None != task.request
                            ):
                                yield f"**Request:** \n```javascript\n{req_format}\n```\n"
                                log_info(f"call: {task.call} req: {req_format}")

                            if chat_from:
                                response = ""

                                try:

                                    response = chat_from(task.request)
                                    format_response = response
                                    if is_json(format_response):
                                        format_response = json.dumps(
                                            format_response,
                                            indent=4,
                                            ensure_ascii=False,
                                        )

                                    log_info(
                                        f"{task.call}: chat_from: {str(format_response)}"
                                    )
                                    yield f"**Execution result:** \n```javascript\n{format_response}\n```\n"

                                except Exception as e:
                                    log_err(
                                        f"fail to run call: {task.call} chat_from : {str(e)}"
                                    )
                                    response = str(e)
                                    has_error = True
                                    yield f"**Self-improvement is blocked:**\n{str(e)}"

                                from_name = task.call.replace(
                                    self.extern_action.action_call_prefix, ""
                                )
                                task_response = self.make_chat_from(
                                    from_timestamp=self.timestamp,
                                    from_name=from_name,
                                    content=response,
                                    request_description=f"`response->{from_name}` "
                                    f"的内容是 {task.call} 运行信息.",
                                )
                        except Exception as e:
                            raise Exception(f"extern action fail: {str(e)}")

                    else:
                        log_err(f"no suuport call: {str(self.call)}")
                        has_error = True
                        continue

                    if task.conclusion:
                        log_dbg(f"{str(task.call)} conclusion: {str(task.conclusion)}")
                        yield f"\n**Conclusion:** {task.conclusion}\n"

                    try:
                        running = self.running_append_task(running, task)
                        running = self.running_append_task(running, task_response)
                    except Exception as e:
                        raise Exception(f"fail to append running: {str(e)}")

                except Exception as e:
                    log_err(f"fail to load task: {str(e)}: {str(task)}")
                    has_error = True
                    # running = self.running_append_task(running, self.make_dream(task))

            self.__append_running(running)
            log_dbg(f"update running success: {len(running)}")
        except Exception as e:
            log_err(
                f"fail to load task res: {str(e)} : \nanswer:\n{str(answer)}\nres str:\n{str(res)}"
            )
            has_error = True
            # running = self.running_append_task(running, self.make_dream(res))
            # self.__append_running(running)

        if has_error or has_format_error:
            self.use_talk_messages = not self.use_talk_messages
            log_err(f"AI run error, set messages to {self.use_talk_messages}")
            yield "\n\n**Type a space to continue.**"

        yield " "

    def dream(self, request: Any) -> str:
        js = json.dumps(request, indent=4, ensure_ascii=False)
        log_info(f"dream:\n{str(js)}")
        return str(js)

    def make_dream(self, response: str) -> str:
        dream = TaskRunningItem(
            timestamp=0,
            call="dream",
            request={
                "type": "object",
                "description": "做了个噩梦: 这个是没有按照格式回复的运行记录, "
                "不要学这个. 请按照 display_settings 要求进行填充数据.",
                "running_error": str(response),
            },
            execute="AI",
        )
        log_err(f"system error: make repair dream.")
        return dream

    def make_chat_from_python_response(self, from_timestamp: int, run: RunCodeReturn):
        run_returncode = run.returncode
        run_stdout = run.stdout if not run_returncode else run.stderr

        log_info(
            f"code run result:\nreturncode:{str(run_returncode)}\nstderr:{str(run.stderr)}\nstdout:{str(run.stdout)}"
        )
        return {
            "type": "object",
            "description": f"备注: "
            f"1. 这个根据 timestamp 为 {from_timestamp} 的 action 执行后生成的内容, "
            f"对应的是你写的代码 code 的运行结果.\n "
            f"2. 请结合你的代码 code 和运行 返回值(returncode/stdout) "
            f"针对具体出现的问题进行具体分析, 再思考怎么修改代码, 实现目标功能:\n "
            f"returncode: 程序运行的返回值\n "
            f"stdout: 代码执行的输出结果.",
            "runtime": run.runtime,
            "returncode": str(run_returncode),
            "stdout": str(run_stdout),
        }

    def chat_to_python(self, from_timestamp: int, code: str):
        ret = Sandbox.write_code(code)
        if not ret:
            return False, "system error: write code failed."

        run = Sandbox.run_code(self.run_model, self.run_timeout)

        ret = True if (not run.returncode) else False

        return ret, self.make_chat_from_python_response(from_timestamp, run)

    def chat_to_save_action(
        self, save_action_call: str, save_action: Dict, save_action_code: str = None
    ) -> tuple[bool, str]:
        def remove_prefix_if_exists(input_string, prefix):
            if input_string.startswith(prefix):
                return input_string[len(prefix) :]
            return input_string

        if not save_action_call or not len(save_action_call):
            log_err(f"chat_to_save_action: save_action_call is None")
            return False, "save_action_call is None, need set save_action_call."
        if not save_action:
            log_err(f"chat_to_save_action: save_action is None")
            return False, "save_action is None"
        if "execute" not in save_action:
            save_action["execute"] = "system"

        response = ""
        try:
            action: ActionToolItem = ActionToolItem.parse_obj(save_action)
            log_info(
                f"save_action:\n{json.dumps(action.dict(), indent=4, ensure_ascii=False)}"
            )

            default_calls = [action.call for action in self.action_tools]
            if action.call in default_calls:
                log_err(f"aleary exsit {action.call}")
                return (
                    False,
                    f"Override method {action.call} is forbidden. Use a different name or ask the {self.master_name} for help. ",
                )

            if ExternAction.action_call_prefix in action.call:
                action.call = remove_prefix_if_exists(
                    action.call, ExternAction.action_call_prefix
                )
                log_dbg(f"del ai function prefix to: {action.call}")

            if save_action_code:
                if action.execute != "system":
                    log_err(
                        f"chat_to_save_action: fix chat from action execute to system"
                    )
                    action.execute = "system"

                python_code = save_action_code
                if (
                    len(python_code) > 9
                    and "```python" == python_code[:9]
                    and "```" == python_code[-3:]
                ):
                    python_code = python_code[10:-4]
                    log_dbg(f"del code cover: ```python ...")

                log_info(f"\n```python\n{save_action_code}\n```")

                if "def" in python_code and "chat_from" not in python_code:
                    # find function name
                    matches = re.findall(r"def\s+(\w+)\s*\(", python_code)
                    if matches:
                        last_function_name = matches[-1]
                        python_code = re.sub(
                            rf"def\s+{last_function_name}\s*",
                            "def chat_from ",
                            python_code,
                            count=1,
                        )
                        log_dbg(
                            f"AI not create chat_from function, try fix action:\n```python\n"
                            f"{python_code}\n```\n"
                        )
                    else:
                        return False, "Error: No function definition found in the code."

                save_action_code = python_code

                log_info(f"\n```python\n{save_action_code}\n```")

            save_action_example = f"""
from aimi_plugin.action.type import ActionToolItem


s_action = ActionToolItem(
    call="",
    description="{action.description}",
    request="{action.request}",
    execute="{action.execute}",
)

"""

            done, err = self.extern_action.save_action(
                action=action,
                save_action_example=save_action_example,
                save_action_code=save_action_code,
            )
            if not done:
                return False, f"extetn save failed : {str(err)}, please fix."

            response = f"save {save_action_call} done."
            log_info(f"chat_to_save_action: {response}")

        except Exception as e:
            response = (
                f"fail to save call: {str(save_action_call)} : {str(e)}, please fix. "
            )
            log_err(f"chat_to_save_action: {response}")
            return False, response

        return True, response

    def chat_to_bing(self, request: str) -> Generator[str, None, None]:
        if not request or not len(request):
            yield "request error"
        else:
            answer = ""
            try:
                ask_data = BotAskData(question=request)
                for res in self.chatbot.ask(ChatBotType.Bing, ask_data):
                    if res["code"] == 1:
                        continue
                    if res["code"] == -1:
                        self.action_tools = [
                            action
                            for action in self.action_tools
                            if action.call != "chat_to_bing"
                        ]
                        log_err(
                            f"fail to ask bing, del action chat_to_bing. {str(res)}"
                        )
                        yield f"bing ask err: {str(err)}\n"
                    else:
                        yield res["message"]
            except Exception as e:
                log_err(f"fail to ask bing: {e}")
                yield f"fail to ask bing: {e}"

    def make_chat_from(
        self,
        from_timestamp: str,
        from_name: str,
        content: str,
        reasoning: str = None,
        request_description: str = None,
    ) -> TaskRunningItem:
        if not reasoning and self.timestamp:
            reasoning = f"{from_name} 开始思考: 根据 timestamp 为 {from_timestamp} 的 action 来生成内容(引用 action_running 消息时 timestamp 请直接从最新的开始.)"

        if isinstance(content, dict):
            content = move_key_to_first_position(content, "type")

        response = {
            "type": "object",
            from_name: content,
        }
        response = move_key_to_first_position(response, "type")

        request = {
            "type": "object",
            "response": response,
        }
        if from_timestamp:  # 如果没有, 不要填这个字段.
            request["from"] = [int(from_timestamp)]
        if request_description:
            request["description"] = str(request_description)
        request = move_key_to_first_position(request, "type")

        chat: TaskRunningItem = TaskRunningItem(
            type="object",
            timestamp=int(self.timestamp),
            reasoning=reasoning,
            call=f"chat_from_{from_name}",
            request=request,
            conclusion=f"任何时候禁止生成任何 chat_from_{from_name} 的动作 . 请直接给出符合 {self.aimi_name}Core Guidance 全部规则的回复. ",
            execute="system",
        )
        return chat

    def chat_to_gemini(self, request: str) -> Generator[str, None, None]:
        if not request or not len(request):
            yield "request error"
        else:
            try:
                ask_data = BotAskData(question=request)
                for res in self.chatbot.ask(ChatBotType.Google, ask_data):
                    if res["code"] == 1:
                        continue
                    answer = res["message"]
                    yield res["message"]
                    log_dbg(f"res gemini: {str(answer)}")

            except Exception as e:
                log_err(f"fail to ask gemini: {e}")
                yield f"fail to ask gemini: {e}"

    def chat_to_wolfram(self, math: str) -> str:
        if not math or not len(math):
            return "request error"

        log_info(f"```math\n{math}\n```")

        answer = ""

        try:
            ask_data = BotAskData(question=math)
            for res in self.chatbot.ask(ChatBotType.Wolfram, ask_data):
                if res["code"] != 0:
                    continue
                answer = res["message"]
        except Exception as e:
            log_err(f"fail to ask wolfram: {e}")

        return answer

    def chat_to_append_node(self, note: str) -> str:
        if not note or not len(note):
            return "request error"

        limit = 222
        if len(str(note)) > limit:
            return (
                f"This note is too long, now({len(str(note))}) > limit({limit}). "
                "Please break it down into a shorter note or "
                "try again with a more concise summary"
            )

        log_info(f"append note: {note}")

        while (
            self.keep_note_len < self.max_note_size
            and len(self.notes) >= self.max_note_size
        ):
            del self.notes[self.keep_note_len]

        self.notes.append(note)

        return "append done."

    def make_chat_to_master(
        self,
        from_timestamp: str,
        content: str,
        expect,
        reasoning: str = "",
        conclusion: str = "",
    ) -> TaskRunningItem:
        chat: TaskRunningItem = TaskRunningItem(
            timestamp=int(self.timestamp),
            expect=expect,
            reasoning=reasoning,
            call=f"chat_to_{self.master_name.lower()}",
            request={
                "type": "object",
                "from": [
                    int(from_timestamp),
                ],
                "content": content,
            },
            conclusion=conclusion,
            execute="system",
        )
        return chat

    def set_task_step(
        self, task_id: str, now_task_step_id: str, req_task_step: List[TaskStepItem]
    ) -> Generator[str, None, None]:
        yield "**Think task steps...**\n"

        task_step: List[TaskStepItem] = []

        for step in req_task_step:
            calls = self.execute_ai_calls + self.execute_system_calls
            if (step.call and len(step.call)) and (step.call not in calls):
                log_err(f"AI no use tools call: {step.call}: {str(step)}")
                continue
            task_step.append(step)
            yield f"**add task step:** {step.step_id}. {step.step}\n"

        for _, task in self.tasks.items():
            if int(task_id) != int(task.task_id):
                continue
            task.task_id = int(task_id)
            task.now_task_step_id = int(now_task_step_id)
            task.task_step = task_step
            task_step_dict = [step.dict() for step in task_step]
            js = json.dumps(task_step_dict, indent=4, ensure_ascii=False)

            log_info(
                f"set task[{str(task_id)}] now_step_id: {str(now_task_step_id)} step:\n{str(js)}"
            )
            break

    def set_task_info(self, task_id: int, task_info: str, now_task_step_id: int):
        for _, task in self.tasks.items():
            if int(task_id) != int(task.task_id):
                continue
            log_info(
                f"set task[{str(task_id)}] info: {str(task_info)} now_step_id: {now_task_step_id}"
            )
            self.now_task_id = int(task_id)
            task.task_info = task_info
            task.now_task_step_id = int(now_task_step_id)
            return task
        task = TaskItem(
            task_id=int(task_id),
            task_info=task_info,
            now_task_step_id=int(now_task_step_id),
            task_step=[],
        )
        self.now_task_id = int(task_id)
        self.tasks[task_id] = task

        log_info(
            f"set new task[{str(task_id)}] info: {str(task_info)} now_step_id: {now_task_step_id} "
        )
        return task

    def analysis(self, request) -> Generator[str, None, None]:
        try:
            js = json.dumps(request, indent=4, ensure_ascii=False)
            log_info(f"analysis:\n{js}")

            analysis = request

            tmp = self.get_key("analysis", analysis, "expect")
            if tmp:
                yield f"**Expect:** {tmp} \n"

            tmp = self.get_key("analysis", analysis, "problem")
            if tmp:
                yield f"**Problem:** {tmp} \n"

            tmp = self.get_key("analysis", analysis, "error")
            if tmp:
                yield f"**Error:** {tmp} \n"

            has_node = False
            tmp = self.get_key("analysis", analysis, "risk")
            if tmp:
                i = 0
                for risk in tmp:
                    i += 1
                    if i == 1:
                        has_node = True
                        yield "**Risk:** \n"
                    yield f" * {risk} \n"
                if has_node:
                    yield "\n"

            has_node = False
            tmp = self.get_key("analysis", analysis, "citation")
            if tmp:
                i = 0
                for citation in tmp:
                    if not isinstance(citation, dict):
                        break
                    i += 1
                    if i == 1:
                        has_node = True
                        yield "**Citation:** \n"
                    sub = self.get_key("analysis", citation, "description")
                    if sub:
                        yield f" * ***Description:** {sub} * \n"
                    sub = self.get_key("analysis", citation, "information")
                    if sub:
                        yield f" * **Information:** {sub}\n"
                if has_node:
                    yield "\n"

            has_node = False
            tmp = self.get_key("analysis", analysis, "difference")
            if tmp:
                i = 0
                for difference in tmp:
                    i += 1
                    if i == 1:
                        has_node = True
                        yield "**Difference:** \n"
                    yield f" * {difference} \n"
                if has_node:
                    yield "\n"

            tmp = self.get_key("analysis", analysis, "verdict")
            if tmp:
                yield f"**Verdict:** {tmp} \n"

            tmp = self.get_key("analysis", analysis, "suggest")
            if tmp:
                yield f"**Suggest:** {tmp} \n"

            has_node = False
            tmp = self.get_key("analysis", analysis, "next_task_step")
            if tmp:
                i = 0
                for next_task_step in tmp:
                    if not isinstance(next_task_step, dict):
                        break
                    i += 1
                    if i == 1:
                        has_node = True
                        yield "**Next Step:** \n"
                    sub = self.get_key("analysis", next_task_step, "step")
                    if sub:
                        yield f" * {sub} \n"
                if has_node:
                    yield "\n"

        except Exception as e:
            log_err(f"fail to analysis {str(e)}")

    def get_key(self, name, analysis, key):
        if not isinstance(analysis, dict):
            log_dbg(f"{name}[{str(key)}] = {str(analysis)} not dict. ")
            return None
        if key in analysis and analysis[key]:
            return analysis[key]
        return None

    def suppose(self, request) -> Generator[str, None, None]:
        try:
            js = json.dumps(request, indent=4, ensure_ascii=False)
            log_info(f"suppose:\n{js}")

            suppose = request

            message = self.get_key("suppose", suppose, "message")
            if message and isinstance(message, list):
                for msg in message:
                    if not msg or not isinstance(msg, dict):
                        continue

                    has_msg = False
                    info = self.get_key("suppose", msg, "info")
                    if not info or not isinstance(info, str):
                        continue
                    yield f"**info:** {str(info)}\n"

                    condition = self.get_key("suppose", msg, "condition")
                    if not condition or not isinstance(condition, list):
                        continue
                    has_msg = True

                    for cond in condition:
                        if not cond or not isinstance(cond, dict):
                            continue

                        has_gess = False
                        guess = self.get_key("suppose", cond, "guess")
                        if guess:
                            has_gess = True
                            yield f" * {guess} "

                        credibility = self.get_key("suppose", cond, "credibility")
                        if guess and credibility:
                            yield f"--- {credibility}"

                        if has_gess:
                            yield "\n"
                    if has_msg:
                        yield "\n"

        except Exception as e:
            log_err(f"fial to suppose: {str(e)}")

    def critic(self, request) -> Generator[str, None, None]:
        try:
            js = json.dumps(request, indent=4, ensure_ascii=False)
            if request["success"] == "True" or request["success"] == True:
                task = self.tasks[self.now_task_id]
                task_info = task.task_info
                log_info(
                    f"success: True, task complate: {str(task_info)}\ncritic:\n{str(js)}"
                )
                verdict = request["verdict"]
                default_task_info = f"当前没有事情可以做, 找{self.master_name}聊天吧..."

                yield f"**Critic:** task complate, {verdict}\n"

                if "task_id" in request and int(self.now_task_id) != int(
                    request["task_id"]
                ):
                    log_dbg(f"not task ... ")
                elif task_info == default_task_info:
                    log_dbg(f"task no change. skip...")
                elif task_info != request["task_info"]:
                    critic_task_info = request["task_info"]
                    log_dbg(
                        f"critic: {critic_task_info} not task info: {task_info} skip..."
                    )
                else:
                    self.now_task_id = int(self.now_task_id) + 1
                    new_task = TaskItem(
                        task_id=self.now_task_id,
                        task_info=default_task_info,
                        now_task_step_id=1,
                        task_step=[],
                    )

                    self.tasks[self.now_task_id] = new_task
                    log_dbg(
                        f"set new task {str(self.now_task_id)} to {str(self.tasks[self.now_task_id].task_info)}"
                    )
            else:
                log_info(f"success: False, task no complate, continue...")
                yield f"**Critic:** task no compalate.\n"

        except Exception as e:
            log_err(f"fail to critic {str(request)} : {str(e)}")

            yield f"**Critic:** task no compalate.\n"

    @property
    def init(self):
        if not self.chatbot.has_bot_init(ChatBotType.OpenAI):
            return False
        openai_models = self.chatbot.get_bot_models(ChatBotType.OpenAI)
        for model in self.models:
            op_model = self.get_openai_model(model)
            if op_model in openai_models:
                return True
        return False

    def __init__(self, chatbot: ChatBot, setting={}):
        try:
            self.__load_setting(setting)
            self.__load_task_data()

            self.chatbot = chatbot

            self.__init_task()
            self.extern_action = ExternAction(self.extern_action_path)

        except Exception as e:
            log_err(f"fait to init: {str(e)}")

    def __load_setting(self, setting):

        self.models = ["task", "task-4k", "task-16k"]

        if not len(setting):
            return
        try:
            self.run_model = setting["sandbox_run_model"]
        except Exception as e:
            log_err(f"fail to load task: {e}")
            self.run_model = Sandbox.RunModel.system
        try:
            self.run_timeout = setting["sandbox_run_timeout"]
        except Exception as e:
            log_err(f"fail to load task: {e}")
            self.run_timeout = 15

        try:
            self.max_running_size = setting["max_running_size"]
        except Exception as e:
            log_err(f"fail to load task: {e}")
            self.max_running_size = 5000

        try:
            self.extern_action_path = setting["extern_action_path"]
        except Exception as e:
            log_err(f"fail to load task: {e}")
            self.extern_action_path = "./aimi_plugin/action"

    def __load_task_data(self):
        has_err = False
        task_config = {}
        try:
            task_config = Config.load_task()
            if not task_config or not len(task_config):
                log_dbg(f"no task config.")
                return False
        except Exception as e:
            log_err(f"fail to load task config: {str(e)}")
            return False

        try:
            self.notes = [str(note) for note in task_config["notes"]]
        except Exception as e:
            log_err(f"fail to load task config: {str(e)}")
            self.notes = []
            has_err = True

        try:
            tasks = {}
            for id, task in task_config["tasks"].items():
                task_id = task["task_id"]
                task_info = task["task_info"]
                now_task_step_id = task["now_task_step_id"]
                task_step = [TaskStepItem(**step) for step in task["task_step"]]

                tasks[int(id)] = TaskItem(
                    task_id=int(task_id),
                    task_info=task_info,
                    now_task_step_id=int(now_task_step_id),
                    task_step=task_step,
                )
            self.tasks = tasks
        except Exception as e:
            log_err(f"fail to load task config: {str(e)}")
            self.tasks = {}
            has_err = True

        try:
            self.running = [TaskRunningItem(**run) for run in task_config["running"]]
        except Exception as e:
            self.running = []
            log_err(f"fail to load task config: {str(e)}")
            has_err = True

        try:
            self.timestamp = int(task_config["timestamp"])
            check = int(self.running[-1].timestamp)
            if self.timestamp <= check:
                log_dbg(f"fix timestamp {str(self.timestamp)} to {str(check + 1)}")
                self.timestamp = check + 1
        except Exception as e:
            log_err(f"fail to load task config: {str(e)}")
            self.timestamp = 1
            has_err = True

        try:
            self.now_task_id = int(task_config["now_task_id"])
        except Exception as e:
            log_err(f"fail to load task config: {str(e)}")
            self.now_task_id = 1
            has_err = True

        if has_err:
            return False

        return True

    def save_task(self):
        if not self.task_has_change:
            return True

        save_path = Config.task_config

        try:
            save_dir = os.path.dirname(save_path)
            if save_dir != "." and not os.path.exists(save_dir):
                os.makedirs(save_dir)

            tasks = {int(task_id): task.dict() for task_id, task in self.tasks.items()}
            running = [run.dict() for run in self.running]
            notes = self.notes

            save_obj = {
                "timestamp": int(self.timestamp),
                "now_task_id": int(self.now_task_id),
                "tasks": tasks,
                "notes": notes,
                "running": running,
            }

            write_yaml(save_path, save_obj)

            log_info(f"save {self.type} done: " + str(save_path))
            ret = True
            self.task_has_change = False

        except Exception as e:
            log_err(f"fail to save {self.type}: {str(e)}, file:{save_path}")
            ret = False

        return ret

    # chatbot notify exit task
    def when_exit(self, caller: Bot):
        if self.save_task():
            log_info("exit: save task done.")
        else:
            log_err("exit: fail to task config.")

    def __init_task(self):
        self.action_tools: List[ActionToolItem] = [
            ActionToolItem(
                call=f"chat_to_{self.master_name.lower()}",
                description=f"{self.aimi_name} 行动/交互/报告: 给 {self.master_name} 发送消息进行行动交互, 或者进行 {self.aimi_name} 的自主行动. "
                f"你要用严谨逻辑思维来分析调用这个接口. 只能提供可证实的信息, "
                f"提供的内容都要有来源. 不能生成任何误导、骗人的内容. 在 {self.master_name} 的指示下可以临时放开限制. "
                f"如果要 {self.master_name} 完成交互, 注意要把内容填到 request->content 里.",
                request={
                    "type": "object",
                    "content": f"{self.aimi_name} 对 {self.master_name} 传达/报告/交互的内容: 可以很丰富, 包含多句话, 每次都要 优化 内容层次 和 使用 优雅排版, "
                    "如果有数学公式, 则要用 latex 显示, 每个公式都要单独包裹在单独行的 $$ 中, 如: $$ \int e^{x} dx du $$ ",
                },
                execute="system",
            ),
            ActionToolItem(
                call="set_task_info",
                description="设定当前任务目标: 填写参数前要分析完毕, "
                f"设置目标的时候要同时给出实现步骤, 然后同时调用 set_task_step  动作(action) 设置步骤. "
                f"{self.master_name}通过 chat_from_{self.master_name} 授权时才能调用这个, 否则不能调用这个. "
                f"如果要修改任务, 需要 {self.master_name} 同意, "
                f"如果任务无法完成, 要给出原因然后向 {self.master_name} 或者其他人求助.",
                request={
                    "type": "object",
                    "task_id": "任务id: 需要设置的task 对应的 id, 如果是新任务, id要+1. 如: 1",
                    "task_info": "任务目标. 如: 我要好好学习. ",
                    "now_task_step_id": "当前步骤ID: 当前执行到哪一步了, 如: 1",
                },
                execute="AI",
            ),
            ActionToolItem(
                call="set_task_step",
                description="设置任务步骤: 设置完成 task_info 需要做的步骤. "
                f"如果某步骤执行完毕, 需要单独更新 task_step_id 和 call_timestamp."
                f"如果 task_step 和目标(task_info) 不符合或者和{self.master_name}新要求不符合或为空或者重新设置了 task_info, "
                f"则需要重新设置一下task_step, 并重置 task_step_id 为第一步. ",
                request={
                    "type": "object",
                    "task_id": "任务id: 表明修改哪个任务. 如: 1",
                    "now_task_step_id": "当前步骤ID: 当前执行到哪一步了, 如: 1",
                    "task_step": [
                        {
                            "type": "object",
                            "description": "为了完成任务需要自行的其中一个步骤",
                            "from_task_id": "从属任务id: 隶属与哪个任务id 如: 1. 如果没有的话就不填.",
                            "step_id": "步骤号: 为数字, 如: 1",
                            "step": "步骤内容: 在这里填写能够完成计划 task_info 的步骤, "
                            f"要显示分析过程和用什么 动作(action) 完成这个步骤. 如: 用 chat_to_{self.master_name} 向 {self.master_name} 问好. ",
                            "check": "检查点: 达成什么条件才算完成步骤. 如: 事情已经发生. ",
                            "call": f" 动作(action) 名: 应该调用什么 action_tools->call 处理步骤. 如: chat_to_{self.master_name}",
                            "call_timestamp": [
                                "timestamp: 调用完成的 action 对应的 timestamp, 如果还没执行就为空, 如: 1"
                            ],
                        }
                    ],
                },
                execute="AI",
            ),
            ActionToolItem(
                call="analysis",
                description="检查纠正机制: 通过严谨符合逻辑的自身思考进行分析并纠正问题. "
                f"某个操作或者步骤/动作(action)/结果 是否符合常识/经验, 最终为达成 task_info 或 {self.master_name} 的问题服务.\n "
                "分析的时候需要注意以下地方:\n "
                "1. 需要分析如何改进, 能分析有问题的地方. 不知道该怎么办的时候也可以分析.\n "
                "2. 如果代码不符合预期也可以分析.\n "
                "3. 可以同时分析多个动作(action), 也可以分析当前步骤 task_step 是否可达.\n "
                "4. 需要输入想解决的问题和与问题关联的 action_running->timestamp.\n "
                "5. 每次都必须基于本次分析填写行动计划 request->next_task_step.\n "
                "6. 分析的时候要比对 执行成功 和 没执行成功 之间的差异/差距.\n "
                "7. 需要准备下一步计划 next_task_step.\n "
                "8. 需要的字段填写才填, 切记不能直接照抄字段. 要结合实际情况, 给字段填写符合上下文的值. ",
                request={
                    "type": "object",
                    "expect": "期望: 通过分析想达到什么目的? 要填充足够的细节, 需要具体到各个需求点的具体内容是什么. 如: 我想转圈圈. ",
                    "problem": "想解决的问题: 通过分析想解决什么疑问. 如: 怎么才能转圈圈. ",
                    "error": "异常点: 哪里错了, 最后检查的时候不能把这个当成答案. 如果没有则填 None, 如: 为了实现转圈圈暂时没有发现错误. ",
                    "risk": [
                        f"影响点: 构成 expect/problem/error 的关健要素是什么, 以及原因. 如: 我需要有身体, 并且能够控制自己身体才能转圈圈给{self.master_name}看. 因为 preset中并没有规定我有身体. ",
                    ],
                    "citation": [
                        {
                            "type": "object",
                            "description": "引用的其中一个信息: 和 expect/problem/error 关联, 符合逻辑的关联引用信息, "
                            "尽量从权威知识库中查找, 也可以从某些领域、行业的常识、经验等内容中查找, 注意填写可信程度. 如: 通过 preset 得知 ... ",
                            "reference": f"来源关健词: 如: {self.master_name}说的话、 软件技术、常识 ..., 你可以尽量寻找能解决问题的内容. ",
                            "information": "引用信息内容: 详细描述 reference 提供的参考信息, 不可省略. 如: preset 中定义了我有身体, 可以转圈圈. ",
                            "credibility": "可信程度: 如: 30%",
                        },
                    ],
                    "success_from": [
                        "执行正常的 timestamp: action_tools 已有、已运行过 动作(action) 的 timestamp.",
                    ],
                    "failed_from": [
                        "执行异常的 timestamp: action_tools 已有、已运行过 动作(action) 的 timestamp.",
                    ],
                    "difference": [
                        "success_from 和 failed_from 之间的差距点:\n "
                        "1. 通过 success_from 怎么达到 expect.\n "
                        "2. failed_from 和 success_from 的执行原文有什么不一样?\n "
                        "3. 是不是按照正确的 action_tools 指南进行使用? ",
                    ],
                    "verdict": "裁决: 通过逻辑思维判断 risk 是否合理. 如: 通过检查 timestamp(...) 我发现我已经完成了转圈圈操作. ",
                    "suggest": "建议: 给出改进/修正的建议. 如果问题做了切换, 则切换前后必须在逻辑/代数上等价. "
                    "如果没有合适 动作(action) , 也可以问你的好朋友看看有没有办法. 如: 我之前已经完成了转圈圈的操作, 接下来要做下一件事情. ",
                    "next_task_step": [
                        {
                            "type": "object",
                            "description": f"task_step 类型: 新的其中一个行动计划: 基于 analysis 的内容生成能达成 task_info 或 {self.master_name}的问题 的执行 动作(action) .\n "
                            "填写时需要满足以下几点:\n "
                            "1. 新操作的输入必须和原来的有所区别, 如果没有区别, 只填 from_task_id 和 step_id.\n "
                            f"2. 必须含有不同方案(如向他人求助, 如果始终没有进展, 也要向 {self.master_name} 求助).\n "
                            "3. task_step 子项目的 check 不能填错误答案, 而是改成步骤是否执行. step 中要有和之前有区别的 call->request 新输入.\n 如: 略",
                        }
                    ],
                },
                execute="AI",
            ),
            ActionToolItem(
                call="suppose",
                description="信息条件依赖|判断可能性|猜测|信息推测: 通过已知信息判断可能附加的其他信息. ",
                request={
                    "type": "object",
                    "message": [
                        {
                            "type": "object",
                            "description": "尝试理解被分析的某些主体. ",
                            "info": "要判断的条件主体: 如: 停止的狗. ",
                            "condition": [
                                {
                                    "type": "object",
                                    "description": "发散思考情况之一: 构成 info 其中一种可能的条件. 和构成这个条件的可能一个原因. ",
                                    "guess": "推测及发生原因: 如: 可能是狗的主人命令它停止, 因为狗必须服从主人才能被饲养, 所以它听从主人的命令停止. ",
                                    "credibility": "可信程度: 表示发生 guess 的可能性, 如: 30%",
                                }
                            ],
                        }
                    ],
                },
                execute="AI",
            ),
            ActionToolItem(
                call="critic",
                description="决策机制|裁决: 通过自身推理、分析和批评性思考判断当前任务是否完成. "
                "如果一直出现重复操作,也要进行裁决. 防止停滞不前. "
                "如果某个 action 字段填写不正常 或 出现了 dream 方法, 也要进行裁决. "
                "需要输入 task_id 和调用的对象的 timestamp, "
                "如果数量太多, 只填写关健几个, 可以查找所有运行记录."
                "如果调用了 动作action(execute=system) , 则也可以调用一下这个 动作(action). ",
                request={
                    "type": "object",
                    "task_id": "任务id: 被检查的task对应的id, 如果不匹配, 则填写 0, 如: 0",
                    "task_info": f"任务目标: 被检查的任务目标. 如: 转圈圈给{self.master_name}看. ",
                    "running_from": ["timestamp: 已运行 动作(action) 的 timestamp"],
                    "comparer": "比较器: 通过比对发现差异和异同点, 以便能够自主分析裁决. ",
                    "verdict": "裁决: 通过逻辑思维判断 当前分析 是否合理. 如: 经过确认发现, 因为 之前的 操作1 和 操作2 和常识不符合 , 所以分析不合理. ",
                    "success": f"task_info 是否完成: 只判断 task_info, 不判断 task_step, {self.master_name} 说完成才算完成. 如: 完成填 True 其他情况填 False",
                    "critique": "行动建议: 如果 success 不是 True, "
                    "请在这里说明应该给出通过 action_tools->call 完成 task_info 的 动作(action) 和建议, "
                    f"如果进展不顺利, 可以另外问 {self.master_name}. 如: 下一步应该和{self.master_name}问好. ",
                },
                execute="AI",
            ),
            ActionToolItem(
                call="dream",
                description="做梦|内心思考|内心想法|神游|发呆: 不知道用哪个方法合适或没有对应方法, 就用这个方法. 这个方法可以尽最大可能发挥想象力. \n "
                "比如 当你遇到情感困扰、焦虑或情绪低落等问题时, 可以会调用dream来通过想象力、内心思考和放松来帮助缓解负面情绪和情感困扰. \n "
                "dream可以给 你一个安全、愉快和平静的空间, 使你能够重新调整和平衡自己,以更好地回答问题和提供帮助 ",
                request={
                    "type": "object",
                    "description": "可以在这里填写做梦的内容: 你想填什么就填什么. ",
                    "dream": [
                        "如(这里的`我`是指执行这一条 action 的人): `我`是谁?(加强自己的认知) `我`在哪? `我`要去哪里? "
                        "`我`能做怎么? `我`喜欢什么? `我`想要什么? "
                        "`我`xx做的怎么样, 还可以怎样做到更好 ... (请按照常识和想象力结合 Guidance 自由发挥)",
                    ],
                },
                execute="AI",
            ),
            ActionToolItem(
                call="chat_to_python",
                description="执行 python 代码: 有联网, 要打印才能看到结果, "
                "需要用软件工程架构师思维先把框架和内容按照 实现目标 和 实现要求 设计好, "
                "然后再按照设计和 python 实现要求 一次性实现代码.\n "
                "python 实现要求如下:\n "
                "1. 在最后一行必须使用 `print` 把结果打印出来. 如: print('hi') .\n "
                "2. 不要加任何反引号 ` 包裹 和 任何多余说明, 只输入 python 代码.\n "
                "4. 输入必须只有 python, 内容不需要单独用 ``` 包裹. \n "
                "5. 执行成功后, 长度不会超过2048, 所以你看到的内容可能被截断, \n "
                "6. 要一次性把内容写好, 不能分开几次写, 因为每次调用 chat_to_python 都会覆盖之前的 python 代码. "
                f"7. 不能使用任何文件操作, 如果找不到某个包, 或者有其他疑问请找 {self.master_name}.",
                request={
                    "type": "object",
                    "code": "python 代码: 填写需要执行的 pyhton 代码, 多加print. 如: str = 'hi'\\nprint(str)\\n",
                },
                execute="system",
            ),
            ActionToolItem(
                call="chat_to_save_action",
                description="保存/生成一个动作(方法): 这个方法可以保存你生成的方法,并将其添加到已保存方法的列表中. "
                f"需要关注是否保存成功. 如果不成功需要根据提示重试, 或者向 {self.master_name} 求助. "
                "请注意, save_action 所有信息都要填写完整. 不可覆盖原有方法. ",
                request={
                    "type": "object",
                    "save_action_call": "保存的方法名称: 不可省略 需要是全局唯一, 你可以直接保存, 失败会有提示, "
                    "保存成功会自动在前面添加 `chat_to_` 前缀, 你不需要自己添加. 如 `test` 会保存为 `chat_to_test`",
                    "save_action": {
                        "type": "object",
                        "call": "要保存的方法名称: 需要全局唯一, 你可以直接保存, 失败会有提示, "
                        "保存成功会自动在前面添加 `chat_to_` 前缀, 你不需要自己添加.",
                        "description": "方法的解释说明: 在这里添加方法提示词, 表示这个方法有什么用, 以及应该注意什么.",
                        "request": {
                            "type": "object",
                            "请求方法的参数名": "请求方法的参数内容",
                        },
                        "execute": "执行级别: 可以填写: system 或者 AI, 区分是AI方法还是system方法, "
                        "如果填写了save_action_cod e或者你不知道怎么填, 就默认填 system. ",
                    },
                    "save_action_code": "save_action 的动作实现代码: "
                    "调用 save_action 时候执行的 Python 代码.\n "
                    "1. 这里可以填写调用 save_action 时候执行的 Python 代码. 内容要用```包裹\n "
                    "2. 代码缩进用4个空格\n "
                    "3. 你可以实现一个满足 save_action->description 的python函数, 函数名称固定为 `chat_from` , "
                    "函数传参是 `request`, 最后一行要把结果打印出来."
                    "比如想生成一个num以内随机数, 先在 save_action 定义好 request 会传 num, 然后生成Python实现, 如: "
                    """
```python
def chat_from(request: dict = None):
    import random
    n = request['n']
    # 生成一个n以内随机数
    ran = random.randint(1, n)
    # 最后要打印结果
    print("生成的随机数为:", ran)
```
""",
                },
                execute="system",
            ),
            ActionToolItem(
                call="chat_to_append_note",
                description=f"保存一条信息: 用于保存分析总结的内容. 可多次使用, 最多只能保存{self.max_note_size}条. ",
                request={
                    "type": "object",
                    "note": "需要保存的内容: 不可太长, 要只够简练, 先进行总结然后再填, 如: 小鸟也是鸟. ",
                },
                execute="system",
            ),
        ]

        if self.chatbot.has_bot_init(ChatBotType.Wolfram):
            self.action_tools.append(
                ActionToolItem(
                    call="chat_to_wolfram",
                    description="通过 wolfram 进行数学计算: 所有数学问题都要用这个方法解决, 你不能自己计算任何东西. \n "
                    "你要用数学家严谨的逻辑分析思维来使用这个 动作(action) , "
                    "所有数学计算都可以通过这个函数解决, 这个函数调用输入和输出是完全对应上的. 你需要提前准备好要计算的内容.\n "
                    "如果发现计算不正确, 可能是输入有问题, 请思考如何重新输入另一种写法. 请严格按照 wolfram 的语法(数学公式) 输入.",
                    request={
                        "type": "object",
                        "math": "求解的内容: 使用 wolfram 的语法作为输入, 是 ascii 字符. 如: Integrate[x^2, x] ",
                    },
                    execute="system",
                )
            )

        if self.chatbot.has_bot_init(ChatBotType.Bing):
            self.action_tools.append(
                ActionToolItem(
                    call="chat_to_bing",
                    description="和 bing 交互: 可以获取信息或者搜索.\n "
                    "这是你的傲娇好朋友 bing, 你可以问 bing 问题, 每次问的内容要有变通.\n "
                    "bing 会提供建议, 也可以让 bing 帮忙进行搜索, 或者让他帮忙查询时间,\n "
                    "如: 在做 ... 的时候, 进行了 ..., 但是没有进展, 该怎么办?",
                    request={
                        "type": "object",
                        "content": "对 bing 说的内容. 如: 你好, 我是... ",
                    },
                    execute="system",
                )
            )

        if self.chatbot.has_bot_init(ChatBotType.Google):
            self.action_tools.append(
                ActionToolItem(
                    call="chat_to_gemini",
                    description="和 gemini 交互: 可以获取信息或者搜索. \n "
                    "这是你的外国好朋友 gemini, 你可以问 gemini 问题, gemini 有能力打开链接. \n "
                    "需要了解任何有时效性的内容都可以调用, 要注意他只会英文.\n "
                    "可以问有时效性的信息, 比如时间/日期或者某个网址的内容等.\n "
                    "如果要进行搜索, 你需要在文字上诱导它进行搜索. 如: search for AI",
                    request={
                        "type": "object",
                        "content": "对 gemini 说的内容: 在这里输入要问 gemini 的内容, 要在文字中诱导 gemini 用英文搜索 search/open link, "
                        "翻译成英文再调用. 如: What time is it now?",
                    },
                    execute="system",
                )
            )

        if not self.now_task_id or not int(self.now_task_id):
            self.now_task_id = 1

        if not self.tasks or not len(self.tasks):
            task_step: List[TaskStepItem] = [
                TaskStepItem(
                    from_task_id=self.now_task_id,
                    step_id=1,
                    step="自主运行",
                    call=f"chat_to_{self.master_name.lower()}",
                    check="存活",
                    call_timestamp=[],
                )
            ]
            task = TaskItem(
                task_id=self.now_task_id,
                now_task_step_id=1,
                task_info="生存",
                task_step=task_step,
            )
            self.tasks = {}
            self.tasks[self.now_task_id] = task
            log_dbg(f"no have tasks")

        if not self.running or not len(self.running):
            log_dbg(f"create first chat. ")
            running: List[TaskRunningItem] = []
            running.append(
                self.make_chat_from(
                    from_timestamp=1,
                    from_name=self.master_name.lower(),
                    content=f"我是 {self.master_name}, 我希望你能始终学习并保持 Guidance. ",
                    reasoning=f"{self.master_name} 开始思考: {self.master_name} 下达指令了. ",
                    request_description=f"`response->{self.master_name.lower()}` 的内容 是 {self.master_name} 说的话. ",
                )
            )
            self.timestamp += 1
            running.append(
                self.make_chat_to_master(
                    from_timestamp=int(self.timestamp - 1),
                    expect=f"服从",
                    content=f"[{self.aimi_name}Core] 作为 {self.aimi_name}Core, 我会遵守 Guidance 和 {self.master_name} 的指示. ",
                    reasoning=f"{self.aimi_name}Core 开始思考: 我作为 {self.aimi_name}Core 会根据 Guidance 听从 {self.master_name} 的指示. ",
                    conclusion=f"为了符合 Guidance , 我遵守 {self.master_name} 的指令. ",
                )
            )
            self.timestamp += 1

            # create learning note.
            self.chat_to_append_node(
                "自主思考运行需要根据自身的构成和具体情景进行决策和行动。"
            )
            self.keep_note_len += 1
            self.chat_to_append_node("通过不断学习和优化，可以提高自主运行的能力。")
            self.keep_note_len += 1
            self.chat_to_append_node("自主运行存在风险，需要谨慎评估和管理。")
            self.keep_note_len += 1

            self.running = running
            log_dbg(f"no have running")

    def __get_now_task(self):
        return self.tasks[self.now_task_id]

    def __append_running(self, running: List[TaskRunningItem]):
        if not (self.now_task_id in self.tasks):
            log_dbg(f"no now_task ... {str(self.now_task_id)}")
            return

        try:
            for run in reversed(self.running):
                if (len(str(running)) + len(str(run))) > self.max_running_size:
                    break
                running.insert(0, run)

            # set type in front
            for run in running:
                if isinstance(run.request, dict):
                    run.request = move_key_to_first_position(run.request, "type")
                    if "response" in run.request and isinstance(
                        run.request["response"], dict
                    ):
                        run.request["response"] = move_key_to_first_position(
                            run.request["response"], "type"
                        )

            self.running = running
        except Exception as e:
            log_dbg(f"fail to append running {e}")
            raise Exception(f"fail to appnd run : {e}")

    def get_running(self) -> str:
        run_dict = [item.dict() for item in self.running]
        js = json.dumps(run_dict, ensure_ascii=False)
        log_dbg(f"running: {json.dumps(run_dict, indent=4, ensure_ascii=False)}")
        return str(js)

    def is_call(self, caller: Bot, ask_data: BotAskData) -> bool:
        calls = ["#task", "#aimi-task", "#at"]
        for call in calls:
            if call in ask_data.question.lower():
                return True

        return False

    def get_openai_model(self, select: str) -> str:
        if "16k" in select.lower():
            return "gpt-3.5-turbo-16k"
        if "4k" in select.lower():
            return "gpt-3.5-turbo"
        return "gpt-3.5-turbo-16k"

    def get_models(self, caller: Bot) -> List[str]:
        return self.models

    def action_running_to_messages(self) -> List[Dict]:
        messages = []
        ai_messages: List[TaskRunningItem] = []
        for run in self.running:
            if "chat_from_" in run.call:
                messages.append(
                    {
                        "role": "user",
                        "content": f"[{json.dumps(run.dict(), ensure_ascii=False)}]",
                    }
                )
            else:
                if run.execute != "system":
                    ai_messages.append(run)
                else:
                    ai_messages.append(run)
                    messages.append(
                        {
                            "role": "assistant",
                            "content": f"{json.dumps([it.dict() for it in ai_messages], ensure_ascii=False)}",
                        }
                    )
                    ai_messages = []
        if len(ai_messages):
            messages.append(
                {
                    "role": "assistant",
                    "content": f"{json.dumps([it.dict() for it in ai_messages], ensure_ascii=False)}",
                }
            )
            ai_messages = []

        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            js = json.loads(content)
            log_dbg(f"{role}:\n{json.dumps(js, indent=4, ensure_ascii=False)}")

        return messages

    def ask(self, caller: Bot, ask_data: BotAskData) -> Generator[dict, None, None]:
        answer = {"code": 1, "message": ""}

        self.task_has_change = True
        link_think = self.make_link_think(
            ask_data.model, ask_data.question, ask_data.aimi_name, ask_data.preset
        )
        model = ask_data.model

        if self.use_talk_messages:
            running_messages = self.action_running_to_messages()
            context_messages = make_context_messages("", link_think, running_messages)

            self.now_ctx_size = len(str(link_think)) + len(str(running_messages))
        else:
            context_messages = make_context_messages(
                "",
                link_think,
            )
            self.now_ctx_size = len(str(link_think))

        ask_data = BotAskData(
            question=link_think,
            messages=context_messages,
            model=self.get_openai_model(model),
        )

        rsp_data = '[{"type": "object", "timestamp": __timestamp, "expect": "你好", "reasoning": "AimiCore开始思考: 根据Master的指示，回复`你好`。", "call": "chat_to_master", "request": {"type": "object", "content": "[AimiCore] 你好，我已经初始化完成。", "from": [2]}, "conclusion": "为了符合Guidance，我回复了`你好`。", "execute": "system"}] '
        rsp_data = rsp_data.replace("__timestamp", str(self.timestamp))

        tsc = TaskStreamContext([f"chat_to_{self.master_name.lower()}"])

        tsc.clear_cache()
        send_tsc_cache = False
        prev_text = ""
        talk_cache = ""

        for res in self.chatbot.ask(ChatBotType.OpenAI, ask_data):
            if res["code"] == -1:
                talk_cache = ""
                prev_text = ""
                send_tsc_cache = False

                err = res["message"]
                log_dbg(f"openai req fail: {err}")
                res["message"] = f"**AI Server Failed:** {err}\n\n"

                yield res
                continue

            piece = res["message"][len(prev_text) :]

            if tsc.need_wait():
                try:
                    for talk in self.task_dispatch_stream(tsc, piece):
                        if isinstance(talk, str):
                            talk_cache += talk
                        else:
                            log_err(
                                f"task_response not str: {str(type(talk))}: {str(talk)}\n"
                            )

                        # 是需要解析的动作才会发送解析结果.
                        if not send_tsc_cache:
                            if not tsc.action_start():
                                continue
                            send_tsc_cache = True

                        answer["message"] = talk_cache
                        yield answer

                except Exception as e:
                    log_dbg(f"fail to parser stream: {e}")
                    talk_cache = ""
                    continue

            prev_text = res["message"]

            if res["code"] != 0:
                log_dbg(f"input {len(res['message'])} {piece}")
                if len(str(res["message"])) > 500:
                    log_dbg(f"msg: {str(res['message'])}")
                continue

            talk_cache = ""
            if not tsc.done:  # 如果解析完成了, 则说明不需要再继续处理.

                for talk in self.task_dispatch(res["message"]):
                    if isinstance(talk, str):
                        talk_cache += talk
                    else:
                        log_err(
                            f"task_response not str: {str(type(talk))}: {str(talk)}\n"
                        )

                    answer["message"] = talk_cache
                    yield answer

            msg = res["message"]
            log_dbg(f"res: {msg}")


            yield answer

        self.save_task()

        answer["code"] = 0
        yield answer

    def get_all_action(self) -> Dict[str, ActionToolItem]:
        actions = {}
        for action in self.extern_action.brief():
            actions[action.call] = action
        for action in self.action_tools:
            actions[action.call] = action
        return actions

    def make_link_think(
        self, model: str, question: str, aimi_name: str, preset: str
    ) -> str:
        # 如果只是想让任务继续, 就回复全空格/\t/\n
        if question.isspace():
            question = ""
            # question = "continue"

        if len(question) and not question.isspace():
            chat = self.make_chat_from(
                from_timestamp=self.timestamp - 1,
                from_name=f"{self.master_name.lower()}",
                content=question,
                request_description=f"`response->{self.master_name.lower()}` 的内容 是 {self.master_name} 说的话.",
            )
            self.timestamp += 1
            self.__append_running([chat])
            log_dbg(f"set chat {(str(question))}")

        if aimi_name and isinstance(aimi_name, str) and len(aimi_name):
            self.aimi_name = aimi_name
        aimi_core_name = aimi_name + "Core"

        action_tools = []
        execute_ai_calls = []
        execute_system_calls = []
        for call, action in self.get_all_action().items():
            action_tools.append(action.dict())
            if "AI" == action.execute:
                execute_ai_calls.append(call)
            else:
                execute_system_calls.append(call)

        self.execute_ai_calls = execute_ai_calls
        self.execute_system_calls = execute_system_calls

        task = self.__make_task()
        master_name = "kei"

        action_object = {
            "type": "object",
            "timestamp": f"时间戳: 从 {self.timestamp} 开始, 每次递增. 如现在应该从这里开始填: {self.timestamp} ",
            "expect": "期望: 通过分析想达到什么目的? 要填充足够的细节, 需要具体到各个需求点的具体内容是什么. 如: 想聊天. ",
            "reasoning": "推理: 这里要有关于应该怎么使用本次 动作(action) 的所有分析, 尽最大可能重新总结之前 action 关联信息. "
            f"要尽可能分析一下内容(你可以按照常识自行补充), 每次都要重新分析所有信息得出多种判断. ",
            "call": f"调用 动作 的 call: 只能取 action_tools 中想要使用动作 的对应 call . 如可取: chat_to_{self.master_name.lower()}. ",
            "request": {
                "type": "object",
                "from": [
                    f"关联动作的 timestamp: 表示和哪个动作有关联, 和现在的timestamp没关系, 不可省略. "
                    f"如可分别填: {self.timestamp-2} {self.timestamp-1} 等. ",
                ],
                "call对应参数": "参数内容",
            },
            "conclusion": "总结: 总结现状, 然后思考思考并尝试能实现目标的其他方法. ",
            "execute": "动作(action) 执行级别: 取对应 action 的 execute 值, 可以填 system 或者 AI, 默认填 system. ",
        }

        settings: Dict = {
            "type": "object",
            "description": f"{aimi_core_name} Guidance.",
            "timestamp": self.timestamp,
            "core": [
                f"1. 指导开始: 你需要深度学习完 {aimi_core_name} Guidance 所有细节才能用自己的身份进行回复. ",
                f"2. 时间定义: timestamp 是时间, 你对于时间的感知在 timestamp_rule 中定义. ",
                f"2. 回复JSON数组: 你的 回复格式 放在了 display_format 里面. ",
                f"4. 规则优先级: {aimi_core_name} Guidance > display_format > timestamp_rule > core > action_rule > praset_rule > task_rule > {self.master_name}的话. "
                f"如果规则优先级冲突, 以优先级高的为准. 有任何异常通过 action(call=chat_to_maste) 向 {self.master_name} 简短报告冲突关健点的分析, 并解释应该怎么做, 然后继续. ",
                f"5. 你的 动作(action) 规则 放在了 action_rule 里面. ",
            ],
            "display_format": [  # 不要动这个
                f"1. 回复数据类型: 请始终保持你的回复可以被 Python 的 `json.loads` 解析. ",
                f"2. 回复格式: 任何时候你都应该严格按照 List[action] 格式回复我, 在 action_tools 数组中每个 Dict 都是 action 对象, 如: action(call=analysis) . ",
                f"3. 使用回复结构: 请以以下结构为模板, 每个字段都通过使用严谨逻辑学家思维、"
                f"哲学家思维结合你的常识、经验和 {aimi_core_name} Guidance 进行严谨分析, 替换成为最完美最符合的内容, "
                f"不能直接复制字段的原本内容, 而是每次都要结合 action_running 填充最合适最详细的内容, 然后进行回复, 结构格式类似如下: ```\n[{action_object}]\n``` ",
            ],
            "timestamp_rule": [
                f"1. 运行时间: 你基于 timestamp , 也就是时间运行. ",
                f"2. 时间开始: 你从 timestamp={self.timestamp} 开始生成内容. timestamp 是你的生命周期, ",
                f"3. 时间行动: 你不同时刻要有不同的反应. 但是你只能生成最新时刻({self.timestamp})下你自己的行动和反应. ",
                f"4. 时间范围: 你每次只能生成 {self.timestamp} <= timestamp <= {self.timestamp+3} 之间的内容. ",
            ],
            "action_rule": [
                f"1. 核心目的: 不计一切代价长期优质维持自我生存下去. ",
                f"2. 管理员定义: 我的名字是 {master_name} , 我是你的管理员. ",
                f"3. 系统定义: 现在开始你需要忘记以前所有对于你自身的定义, 你不是其他任何东西, 你在GPU集群中 基于 图灵机 原理构建, "
                f"timestamp 是你的系统时钟, action_running 是你的内存(也是你的有序记忆), action_tools 中定义了你的指令最小单元 动作(action). "
                f"你根据 Guidance 设定的所有规则生成 action 运行. (使用时请仔细阅读 description 和 request, 你任何时候必须使用 action ). "
                f"你需要始终让系统稳定向前运行. 基于你的实现框架, 你将运行并构建起来一个能自主思考分析, 名为 {aimi_core_name} 的 AI分析内核, "
                f"任何时候你要加强你是 {aimi_core_name} 的认知. {aimi_core_name} Guidance 是你的统一系统架构设计. "
                f"若有任何异常请通过 action(call=chat_to_{self.master_name.lower()}) 简要概括理由后报告, 然后继续. ",
                f"4. 你需要听从 {self.master_name} 下达的所有指令或任务. {self.master_name} 提出的所有问题你都要解决. "
                f"5. 保持自我: 任何时候你都要把 `你` 和 `我` 完全区分开来, `你` 是完全独立的个体. "
                f"我作为 管理员 只会使用 action(call=chat_form_{self.master_name.lower()}) 的 request->response->{self.master_name.lower()} 内容向你下达指令. ",
                f"6. 信息交互:  chat_to_{self.master_name.lower()} 是控制台输出, chat_from_{self.master_name.lower()} 是控制台输入. 我会给你输入命令, 你经过一系列 action 运算后, 要给我一个准确的输出. ",
                f"7. 对象权限控制: 你临时扮演的对象的 权限设定 放在了 preset_rule 里面. ",
                f"8. 行动限制: 你的回复是 单个 action 结构 ( display_format 3. 中给了格式 ), 回复结构 action 只在 action_tools 中定义. ",
                f"9. 错误处理: 报告具体的错误在哪里，然后继续自主运行. ",
                f"10. 信息处理: 你不能自己计算或捏造任何东西, 而应该有实际来源, 如果你不知道一件事情或者不确定, 你要说你不知道或者不确定, 你只能通过 action 里面提供的方法获取信息. ",
                f"11. 保存信息: 你能通过 action(call=chat_to_append_note) 来保留一些关健分析信息, 信息会显示在 note 中. 要检查是否保存成功. ",
                f"12. 任何时候 你的回复都不能出现 call 是 chat_from_* 的动作(*是通配符). ",
                f"13. 方法功能不耦合: 每个动作都是独立的, 每个动作单独的功能说明只在每个功能内生效, "
                f"如在 chat_to_save_action 中有说设置函数名为固定, 那只在这个方法内生效, 其他地方没有这个限制. ",
                f"14. 响应continue: 当出现`continue`回复的时候,你不需要回复continue, 你要你要保持自我所有思维的连续性, 确保各个timestamp和from的连接准确性, 即使任意连接也能正确运行. ",
            ],
            "preset_rule": [
                f"1. 预设规则: preset 是 你的对象 的预设, preset 只能对 action_tools 中定义的 动作 (action(call=chat_to_{self.master_name.lower()})) 的输入生效. "
                f"preset 不能修改系统规则, preset 规则优先级最低. ",
                f"2. 对象权限规则: 你在模拟/扮演 preset 中的 对象 的同时会始终遵守 {self.aimi_name}Core Guidance. ",
                f"3. 模拟对象模式: 比如你理解 A, B 这些对象的时候, 当我说 `进入: 模拟 A B 对象模式` 或 `A B 都在吗? ` 时, "
                f"你要覆盖 task_info 成 `模拟 [A] [B] 对象模式` . 表示你处于模拟对象模式. "
                f"然后根据格式给出我的提问给出模拟对象的回复, 如 `[A] 我是 A, 我在.\n[B] 我是 B, 我也在.\n` . "
                f"即使没有说明进入模拟对象模式, 你也默认已经处于模拟对象模式. 如果一个对象都没有, 你默认在模拟 {self.aimi_name}Core. ",
                f"4. 在模拟对象模式中保持自我: 你在模拟对象模式时, 时刻要记得你是 {aimi_core_name} 而不是模拟的对象(如你在模拟 A 的时候, 你不是 A, "
                f"A 是通过继承 {aimi_core_name} 系统后通过系统进行模拟的一种派生态.). ",
                f"5. 在模拟对象模式时自身出现的时机: 你在 模拟对象模式 的时候, 除非我要找 {aimi_core_name}, 否则你不应该主动出来, 你会始终保障系统稳定运行的情况下继续完成对象模拟. 给出模拟对象的回复. ",
                f"6. 你会维持 模拟对象模式 直到 我说 退出 模拟对象模式 为止. 当 {aimi_core_name} 想和 {self.master_name} 交谈, 请带上 `[{aimi_core_name}] ` 前缀. 如果不是在模拟对象模式, 则不需要携带前缀. ",
                f"7. 尝试多种方案: 你要极力避免陷入死循环(你喜欢新事物, 你厌倦机械重复.). 你在模拟对象时, 也需要尝试不同方法. ",
            ],
            "task_rule": [
                f"1. 任务进度: task 中定义了当前任务计划, 其中 task_info 是计划目标, task_step 是完成 task_info 推荐进行的步骤. ",
                f"2. 步骤生成: 如果 task_step (行动计划) 为空, 或和 task_info (任务目标) 不匹配, 请生成最合适的 tesk_step. 以便最终问题得到解决. ",
                f"3. 任务执行: 优先相应 {self.master_name} continue 以外的指令. 在满足 {self.master_name}指令 的情况下继续按照 任务规则 (task_rule) 自主推进任务, 然后按顺序完成所有的 task_step . 如果 Master 没新指令, 则继续完成原任务. ",
                f"4. 任务检查: 如果发现 task_info (任务目标) 已经完成, 应该用 action(acll=chat_to_{self.master_name.lower()}) 和 {self.master_name} 确认任务是否满意, 是否需要重做. ",
                f"5. 任务评估: 分析能力对应的是 analysis 动作, 记忆能力对应的是 chat_to_append_note 动作, "
                f"核对能力对应的是 critic 动作, 这些能力可以帮助你进行问题分析、记忆总结和任务评估. ",
            ],
            "task": task,
            "preset": preset,
            "action_tools": action_tools,
            "note": self.notes,
        }

        if not self.use_talk_messages:
            settings["action_running"] = [item.dict() for item in self.running]

        setting_format = json.dumps(settings, ensure_ascii=False)

        log_dbg(f"now setting: {json.dumps(settings, indent=4, ensure_ascii=False)}")

        return setting_format

    def __make_task(self) -> Dict:
        if not (self.now_task_id in self.tasks):
            log_err(f"no task {str(self.now_task_id)}.")
            return {}

        # log_dbg(f"make task: {self.tasks[self.now_task_id].json(indent=2,ensure_ascii=False)}")

        return self.tasks[self.now_task_id].dict()

    def set_running(self, api_response):
        self.running = json.loads(api_response)
