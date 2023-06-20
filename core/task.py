import json5
import json
import os
from typing import Dict, Any, List, Generator, Optional, Union
from pydantic import BaseModel, constr

from tool.openai_api import OpenAIAPI
from tool.wolfram_api import WolframAPI
from tool.bard_api import BardAPI
from tool.bing_api import BingAPI
from tool.config import Config
from tool.util import log_dbg, log_err, log_info, make_context_messages, write_yaml
from core.sandbox import Sandbox, RunCodeReturn


class TaskStepItem(BaseModel):
    from_task_id: Optional[Union[str, None]] = None
    step_id: str
    step: str
    check: Optional[Union[str, None]] = ""
    call: Optional[Union[str, None]] = None
    call_timestamp: Optional[Union[List[str], None]] = []


class ActionToolItem(BaseModel):
    type: str = "object"
    call: str
    description: str
    request: Any
    execute: constr(regex="system|AI")


class TaskRunningItem(BaseModel):
    type: str = "object"
    timestamp: str = ""
    reasoning: Optional[Union[str, None]] = None
    call: str
    request: Any
    execute: constr(regex="system|AI")


class TaskItem(BaseModel):
    task_id: str
    task_info: str
    now_task_step_id: str = ""
    task_step: List[TaskStepItem] = []


class Task:
    type: str = "task"
    tasks: Dict[str, TaskItem] = {}
    action_tools: List[ActionToolItem] = []
    system_calls: List[str] = []
    ai_calls: List[str] = []
    now_task_id: str = "1"
    aimi_name: str = "Aimi"
    running: List[TaskRunningItem] = []
    max_running_size: int = 16 * 1000
    timestamp: int = 1
    wolfram_api: WolframAPI
    bard_api: BardAPI
    bing_api: BingAPI
    openai_api: OpenAIAPI

    def task_response(self, res: str) -> Generator[dict, None, None]:
        def get_json_content(answer: str) -> str:
            if "{" == answer[0] and "}" == answer[-1]:
                log_err(f"AI no use format, try add List []")
                return f"[{answer}]"
            start_index = answer.find("```json\n[")
            if start_index == -1:
                start_index = answer.find("[")
            else:
                start_index += 8
            if start_index != -1:
                end_index = answer.rfind("]\n```", start_index)
                if end_index != -1:
                    answer = answer[start_index : end_index + 1]
                else:
                    end_index = answer.rfind("]", start_index)
                    if end_index != -1:
                        if "]" == answer[-1]:
                            # 防止越界
                            answer = answer[start_index:]
                        else:
                            answer = answer[start_index : end_index + 1]
                        # 去除莫名其妙的解释说明
            return answer

        def running_append_task(running: List[TaskRunningItem], task: TaskRunningItem):
            if task and (len(str(running)) + len(str(task))) < self.max_running_size:
                task.timestamp = str(self.timestamp)
                self.timestamp += 1
                running.append(task)
            else:
                log_dbg(f"task len overload: {len(str(task))}")
            return running

        def fill_action_execute(data):
            # fix no execute.
            for action in data:
                for tool in self.action_tools:
                    if "chat_from_" in action["call"] and "execute" not in action:
                        log_err(f"AI try call: chat_from_master")
                        action["execute"] = "system"
                    if action["call"] != tool.call:
                        continue
                    if "execute" in action and action["execute"] != tool.execute:
                        log_err(f"AI try overwrite execute: {tool.call}")
                    action["execute"] = tool.execute
                    log_dbg(f"fill call({tool.call}) execute: {tool.execute}")
            return data

        log_dbg(f"timestamp: {str(self.timestamp)}")
        log_dbg(f"now task: {str(self.tasks[self.now_task_id].task_info)}")

        response = ""
        try:
            answer = get_json_content(res)

            # 忽略错误.
            # decoder = json.JSONDecoder(strict=False)
            # data = decoder.decode(answer)
            data = json5.loads(answer)

            data = fill_action_execute(data)

            tasks = [TaskRunningItem(**item) for item in data]

            running: List[TaskRunningItem] = []
            system_call_cnt = 0
            skip_call = 0
            skip_timestamp = 0
            has_from_master = False
            task_cnt = 1
            for task in tasks:
                try:
                    log_dbg(
                        f"[{task_cnt}] get task: {str(task.call)} : {str(task)}\n\n"
                    )

                    task_cnt += 1
                    task_response = None

                    if int(task.timestamp) < int(self.timestamp):
                        skip_timestamp += 1
                        log_err(
                            f"[{str(skip_timestamp)}] system error: AI try copy old action call: {task.call}"
                        )
                        continue
                    if task.reasoning:
                        log_dbg(f"{str(task.call)} reasoning: {str(task.reasoning)}")

                    if not has_from_master and task.call == "chat_from_master":
                        has_from_master = True

                    if has_from_master:
                        log_err(
                            f"[{str(skip_call)}] system error: AI try predict master call: {task.call}"
                        )
                        continue

                    if task.call in self.system_calls:
                        system_call_cnt += 1

                    if system_call_cnt > 1:
                        skip_call += 1
                        log_err(
                            f"[{str(skip_call)}] system error: AI try predict system call: {task.call}"
                        )
                        continue
                    if "from" in task.request:
                        from_timestamp = str(task.request["from"])
                        log_dbg(f"from_timestamp: {from_timestamp}")

                    if task.call == "chat_to_master":
                        content = str(task.request["content"])
                        log_dbg(f"Aimi: {content}")
                        yield content + "\n"
                    elif task.call == "chat_from_master":
                        log_err(
                            f"{str(task.call)}: AI try predict Master: {str(task.request)}"
                        )
                        continue
                    elif task.call == "set_task_info":
                        task_id: str = task.request["task_id"]
                        task_info: str = task.request["task_info"]
                        now_task_step_id: str = ""
                        if "now_task_step_id" in task.request:
                            now_task_step_id = task.request["now_task_step_id"]
                        self.set_task_info(task_id, task_info, now_task_step_id)
                    elif task.call == "set_task_step":
                        task_id: str = task.request["task_id"]
                        now_task_step_id: str = task.request["now_task_step_id"]
                        request = task.request["task_step"]
                        task_step = []
                        try:
                            task_step = [TaskStepItem(**step) for step in request]
                        except Exception as e:
                            log_err(f"fail to load task_step: {str(e)}: {str(request)}")
                            continue
                        self.set_task_step(task_id, now_task_step_id, task_step)
                    elif task.call == "critic":
                        self.critic(task.request)
                    elif task.call == "analysis":
                        self.analysis(task.request)
                    elif task.call == "chat_to_wolfram":
                        response = self.chat_to_wolfram(task.request["math"])
                        task_response = self.make_chat_from(
                            self.timestamp, "wolfram", response
                        )
                    elif task.call == "chat_to_bard":
                        response = self.chat_to_bard(task.request["content"])
                        task_response = self.make_chat_from(
                            self.timestamp, "bard", response
                        )
                    elif task.call == "chat_to_bing":
                        response = self.chat_to_bing(task.request["content"])
                        task_response = self.make_chat_from(
                            self.timestamp, "bing", response
                        )
                    elif task.call == "chat_to_python":
                        response = self.chat_to_python(task.request["code"])
                        task_response = self.make_chat_from(
                            self.timestamp, "python", response
                        )
                    else:
                        log_err(f"no suuport call: {str(self.call)}")
                        continue

                    running = running_append_task(running, task)
                    running = running_append_task(running, task_response)

                except Exception as e:
                    log_err(f"fail to load task: {str(e)}: {str(task)}")
            self.__append_running(running)
            log_dbg(f"update running success: {len(running)}")
        except Exception as e:
            log_err(f"fail to load task res: {str(e)} : \n{str(res)}")

        yield ""

    def make_chat_from_python_response(self, run: RunCodeReturn):
        run_returncode = run.returncode
        run_stdout = run.stdout
        run_stderr = run.stderr
        log_info(
            f"code run result:\nreturncode:{str(run_returncode)}\nstdout:{str(run_stdout)}\nstderr:{str(run_stderr)}"
        )
        return {
            "description": f"备注: "
            f"1. 这个是 from->timestamp 对应你写的代码 code 的运行结果.\n"
            f"2. 如果 returncode 为 0 但是 stdout 没有内容, 可能是你没有把运行结果打印出来, \n"
            f"3. 如果 stdout/stderr 不正确, 也有可能是你加了非 python 的说明, "
            f"也有可能是你没有把之前写的代码也拼在一起. \n"
            f"4. 请结合你的代码 code 和运行 返回值(returncode/stderr/stdout) 针对具体问题具体分析:\n"
            f"returncode: 程序运行的返回值\n"
            f"stderr: 是你的代码 code 的标准出错流输出, 如果有内容说明出现了错误.\n"
            f"stdout: 是你的代码 code 的标准出错流输出, 你可以检查一下内容是否符合你代码预期.",
            "returncode": str(run_returncode),
            "stderr": str(run_stderr),
            "stdout": str(run_stdout),
        }

    def chat_to_python(self, code: str) -> str:
        if len(code) > 9 and "```python" == code[:9] and "```" == code[-3:]:
            code = code[10:-4]
            log_dbg(f"del code cover: ```python ...")
        log_info(f"code:\n```python\n{code}\n```")
        ret = Sandbox.write_code(code)
        if not ret:
            return "system error: write code failed."

        run: RunCodeReturn = Sandbox.run_code()

        return self.make_chat_from_python_response(run)

    def chat_to_bing(self, request: str) -> str:
        if not request or not len(request):
            return "request error"

        answer = ""
        for res in self.bing_api.ask(request):
            if res["code"] == 1:
                continue
            answer = res["message"]

        return answer

    def make_chat_from(
        self, from_timestamp: str, from_name: str, content: str
    ) -> TaskRunningItem:
        chat: TaskRunningItem = TaskRunningItem(
            timestamp=str(self.timestamp),
            call=f"chat_from_{from_name}",
            request={
                "from": [f"{str(from_timestamp)}"],
                "response": {from_name: content},
            },
            execute="system",
        )
        return chat

    def chat_to_bard(self, request: str) -> str:
        if not request or not len(request):
            return "request error"

        answer = ""
        for res in self.bard_api.ask(request):
            if res["code"] == 1:
                continue
            answer = res["message"]
            log_dbg(f"res bard: {str(answer)}")

        return answer

    def chat_to_wolfram(self, request: str) -> str:
        if not request or not len(request):
            return "request error"
        answer = ""
        for res in self.wolfram_api.ask(request):
            if res["code"] != 0:
                continue
            answer = res["message"]

        return answer

    def make_chat_to_master(
        self, from_timestamp: str, content: str, reasoning: str = ""
    ) -> TaskRunningItem:
        chat: TaskRunningItem = TaskRunningItem(
            timestamp=str(self.timestamp),
            reasoning=reasoning,
            call=f"chat_to_master",
            request={
                "from": [
                    f"{str(from_timestamp)}",
                ],
                "content": content,
            },
            execute="system",
        )
        return chat

    def set_task_step(
        self, task_id: str, now_task_step_id: str, req_task_step: List[TaskStepItem]
    ):
        task_step: List[TaskStepItem] = []
        for step in req_task_step:
            calls = self.ai_calls + self.system_calls
            if (step.call and len(step.call)) and (step.call not in calls):
                log_err(f"AI no use tools call: {step.call}: {str(step)}")
                continue
            task_step.append(step)

        for _, task in self.tasks.items():
            if task_id != task.task_id:
                continue
            task.now_task_step_id = now_task_step_id
            task.task_step = task_step
            task_step_dict = [step.dict() for step in task_step]
            js = json.dumps(task_step_dict, indent=4, ensure_ascii=False)

            log_info(
                f"set task[{str(task_id)}] now_step_id: {str(now_task_step_id)} step:\n{str(js)}"
            )
            return task.task_step

    def set_task_info(self, task_id: str, task_info: str, now_task_step_id: str):
        for _, task in self.tasks.items():
            if task_id != task.task_id:
                continue
            log_info(
                f"set task[{str(task_id)}] info: {str(task_info)} now_step_id: {now_task_step_id}"
            )
            self.now_task_id = task_id
            task.task_info = task_info
            task.now_task_step_id = now_task_step_id
            return task
        task = TaskItem(
            task_id=task_id,
            task_info=task_info,
            now_task_step_id=now_task_step_id,
            task_step=[],
        )
        self.now_task_id = task_id
        self.tasks[task_id] = task

        log_info(
            f"set new task[{str(task_id)}] info: {str(task_info)} now_step_id: {now_task_step_id} "
        )
        return task

    def analysis(self, request):
        try:
            js = json.dumps(request, indent=4, ensure_ascii=False)
            log_info(f"analysis: {js}")
        except Exception as e:
            log_err(f"fail to analysis {str(e)}")

    def critic(self, request):
        try:
            if request["success"] == "True" or request["success"] == True:
                task = self.tasks[self.now_task_id]
                task_info = task.task_info
                log_info(f"success: True, task complate: {str(task_info)}")

                if "task_id" in request and int(self.now_task_id) != int(
                    request["task_id"]
                ):
                    log_dbg(f"not task ... ")
                    return False

                default_task_info = "当前没有事情可以做, 找Master聊天吧..."
                if task_info == default_task_info:
                    log_dbg(f"task no change. skip...")
                    return True

                self.now_task_id = str(int(self.now_task_id) + 1)
                new_task = TaskItem(
                    task_id=self.now_task_id,
                    task_info=default_task_info,
                    now_task_step_id="1",
                    task_step=[],
                )

                self.tasks[self.now_task_id] = new_task
                log_dbg(
                    f"set new task {str(self.now_task_id)} to {str(self.tasks[self.now_task_id].task_info)}"
                )
            else:
                log_info(f"success: False, task no complate, continue...")

        except Exception as e:
            log_err(f"fail to critic {str(request)} : {str(e)}")

    def __init__(self):
        try:
            self.__load_task()
            self.__init_task()
            self.openai_api = OpenAIAPI()
            self.wolfram_api = WolframAPI()
            self.bing_api = BingAPI()
            self.bard_api = BardAPI()

        except Exception as e:
            log_err(f"fait to init: {str(e)}")

    def __load_task(self):
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
            tasks = {}
            for id, task in task_config["tasks"].items():
                task_id = task["task_id"]
                task_info = task["task_info"]
                now_task_step_id = task["now_task_step_id"]
                task_step = [TaskStepItem(**step) for step in task["task_step"]]

                tasks[id] = TaskItem(
                    task_id=task_id,
                    task_info=task_info,
                    now_task_step_id=now_task_step_id,
                    task_step=task_step,
                )
            self.tasks = tasks
        except Exception as e:
            log_err(f"fail to load task config: {str(e)}")
            return False
        try:
            self.running = [TaskRunningItem(**run) for run in task_config["running"]]
        except Exception as e:
            log_err(f"fail to load task config: {str(e)}")
            return False
        try:
            self.timestamp = int(task_config["timestamp"])
            check = int(self.running[-1].timestamp)
            if self.timestamp <= check:
                log_dbg(f"fix timestamp {str(self.timestamp)} to {str(check + 1)}")
                self.timestamp = check + 1

        except Exception as e:
            log_err(f"fail to load task config: {str(e)}")
            return False
        try:
            self.now_task_id = task_config["now_task_id"]
        except Exception as e:
            log_err(f"fail to load task config: {str(e)}")
            return False
        return True

    def save_task(self):
        save_path = Config.task_config

        try:
            save_dir = os.path.dirname(save_path)
            if save_dir != "." and not os.path.exists(save_dir):
                os.makedirs(save_dir)

            tasks = {task_id: task.dict() for task_id, task in self.tasks.items()}
            running = [run.dict() for run in self.running]

            save_obj = {
                "now_task_id": self.now_task_id,
                "tasks": tasks,
                "timestamp": self.timestamp,
                "running": running,
            }

            write_yaml(save_path, save_obj)

            log_info(f"save {self.type} done: " + str(save_path))
            ret = True

        except Exception as e:
            log_err(f"fail to save {self.type}: {str(e)}, file:{save_path}")
            ret = False

        return ret

    def __init_task(self):
        self.action_tools: List[ActionToolItem] = [
            ActionToolItem(
                call="chat_to_master",
                description="和 Master 交互: 给 Master 发送消息进行交互. "
                "你要用严谨逻辑思维来分析调用这个接口. 只能提供可证实的信息, "
                "提供的内容都要有来源. Master 在 Master 的指示下可以临时放开限制. ",
                request={
                    "from": [
                        "有关联的 timestamp: 和哪个 timestamp 的动作(action) 的 request 有关联, 没有则填 null",
                    ],
                    "content": "Aimi 对 Master 传达/报告的内容: 可以很丰富, 包含多句话, 每次都要优化内容层次和优雅排版, "
                    "如果有数学公式, 则要用 latex 显示, 每个公式都要单独包裹在单独行的 $$ 中, 如: $$ \int e^{x} dx du $$ ",
                },
                execute="system",
            ),
            ActionToolItem(
                call="set_task_info",
                description="设定当前任务目标: 填写参数前要分析完毕, "
                "设置目标的时候要同时给出实现步骤, 然后同时调用 set_task_step  动作(action) 设置步骤. "
                "Master通过 chat_from_master 授权时才能调用这个, 否则不能调用这个. "
                "如果要修改任务, 需要 Master 同意, "
                "如果任务无法完成, 要给出原因然后向 Master 或者其他人求助.",
                request={
                    "type": "object",
                    "task_id": "任务id: 需要设置的task 对应的 id, 如果是新任务, id要+1.",
                    "task_info": "任务目标",
                    "now_task_step_id": "当前步骤ID: 当前执行到哪一步了, 如: 1",
                },
                execute="AI",
            ),
            ActionToolItem(
                call="set_task_step",
                description="设置任务步骤: 设置完成 task_info 需要做的步骤. "
                "如果某步骤执行完毕, 需要单独更新 task_step_id 和 call_timestamp."
                "如果 task_step 和目标(task_info) 不符合或者和Master新要求不符合或为空或者重新设置了 task_info, "
                "则需要重新设置一下task_step, 并重置 task_step_id 为第一步. ",
                request={
                    "type": "object",
                    "task_id": "任务id: 表明修改哪个任务",
                    "now_task_step_id": "当前步骤ID: 当前执行到哪一步了, 如: 1",
                    "task_step": [
                        {
                            "type": "object",
                            "from_task_id": "从属任务id: 隶属与哪个任务id 如: 1. 如果没有的话就不填.",
                            "step_id": "步骤号: 为数字, 如: 1",
                            "step": "步骤内容: 在这里填写能够完成计划 task_info 的步骤, "
                            "要显示分析过程和用什么 动作(action) 完成这个步骤.",
                            "check": "检查点: 达成什么条件才算完成步骤",
                            "call": " 动作(action) 名: 应该调用什么 action_tools->call 处理步骤.",
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
                description="分析机制: 通过严谨符合逻辑的自身思考进行分析 "
                "某个操作或者步骤/动作(action)/结果 是否符合常识/经验, 最终为达成 task_info 或 Master 的问题服务.\n"
                "分析的时候需要注意以下地方:\n"
                "1. 需要分析如何改进, 能分析有问题的地方. 不知道该怎么办的时候也可以分析.\n"
                "2. 如果代码不符合预期也可以分析.\n"
                "3. 可以同时分析多个动作(action), 也可以分析当前步骤 task_step 是否可达.\n"
                "4. 需要输入想解决的问题和与问题关联的 action_running->timestamp.\n"
                "5. 每次都必须基于本次分析填写行动计划 request->next_task_step.\n"
                "6. 分析的时候要比对 执行成功 和 没执行成功 之间的差异/差距.\n"
                "7. 需要准备下一步计划 next_task_step. ",
                request={
                    "type": "object",
                    "expect": "期望: 通过分析想达到什么目的? 需要具体到各个需求点.",
                    "problem": "想解决的问题: 通过分析想解决什么疑问.",
                    "error": "异常点: 哪里错了, 最后检查的时候不能把这个当成答案. 如果没有则填 None",
                    "success_from": [
                        "执行正常的 timestamp: action_tool 已有、已运行过 动作(action) 的 timestamp.",
                    ],
                    "failed_from": [
                        "执行异常的 timestamp: action_tool 已有、已运行过 动作(action) 的 timestamp.",
                    ],
                    "difference": [
                        "success_from 和 failed_from 之间的差距点:\n"
                        "1. 通过 success_from 怎么达到 expect.\n"
                        "2. failed_from 和 success_from 的执行原文有什么不一样?\n"
                        "3. 是不是按照正确的 action_tools 指南进行使用?",
                    ],
                    "risk": [
                        "影响点: 构成 expect/problem/error 的要素是什么",
                    ],
                    "verdict": "裁决: 通过逻辑思维判断 risk 是否合理.",
                    "conclusion": "总结: 给出改进/修正的建议. 如果问题做了切换, 则切换前后必须在逻辑/代数上等价. "
                    "如果没有合适 动作(action) , 也可以问你的好朋友看看有没有办法. ",
                    "next_task_step": "task_step array[object]: 新行动计划: 基于 analysis 总结生成能达成 task_info 的执行 动作(action) .\n"
                    "填写时需要满足以下几点:\n"
                    "1. 新操作的输入必须和原来的有所区别, 如果没有区别, 只填 from_task_id 和 step_id.\n"
                    "2. 必须含有不同方案(如向他人求助, 如果始终没有进展, 也要向 Master 求助).\n"
                    "3. task_step 子项目的 check 不能填错误答案, 而是改成步骤是否执行. step 中要有和之前有区别的 call->request 新输入. ",
                },
                execute="AI",
            ),
            ActionToolItem(
                call="critic",
                description="决策机制: 通过自身推理、分析和批评性思考判断当前任务task_info是否完成. "
                "完成后要另外通过 chat_to_master 上报分析结论."
                "需要输入 task_id 和调用的对象的 timestamp, "
                "如果数量太多, 只填写关健几个, 可以查找所有运行记录."
                "如果调用了 动作action(execute=system) , 则也必须调用一下这个 动作(action). ",
                request={
                    "type": "object",
                    "task_id": "任务id: 被检查的task对应的id, 如果不匹配, 则填写 0",
                    "task_info": "任务目标: 被检查的任务目标",
                    "running_from": ["timestamp: 已运行 动作(action) 的 timestamp"],
                    "verdict": "裁决: 通过逻辑思维判断 当前分析 是否合理.",
                    "success": "task_info 是否完成: 只判断 task_info, 不判断 task_step. 完成填 True 其他情况填 False",
                    "critique": "行动建议: 如果 success 不是 True, "
                    "请在这里说明应该给出通过 action_tools->call 完成 task_info 的 动作(action) 和建议, "
                    "如果进展不顺利, 可以另外问 Master.",
                },
                execute="AI",
            ),
            ActionToolItem(
                call="chat_to_wolfram",
                description="通过wolfram进行数学计算: 你要用数学家严谨的逻辑分析思维来使用这个 动作(action) , "
                "所有计算都可以通过这个函数解决, 这个函数调用输入和输出是完全对应上的. "
                "如果发现计算不正确, 可能是输入有问题, 请思考如何重新输入另一种写法. 请严格按照wolfram语言输入.",
                request={
                    "from": [
                        "有关联的 timestamp: 和哪个 timestamp 的动作(action) 的 request 有关联, 没有则填 null",
                    ],
                    "math": "运算内容: 翻译成 wolfram 语言 再调用, 是 ascii 字符. 如: Integrate[x^2, x] ",
                },
                execute="system",
            ),
            ActionToolItem(
                call="chat_to_bard",
                description="和 bard 交互: 这是你的好朋友 bard, "
                "你可以问 bard 问题, bard 有能力打开链接. "
                "需要了解任何有时效性的内容都可以调用, 要注意他只会英文."
                "可以问有时效性的信息, 比如时间/日期或者某个网址的内容等.",
                request={
                    "from": [
                        "有关联的 timestamp: 和哪个 timestamp 的动作(action) 的 request 有关联, 没有则填 null",
                    ],
                    "content": "对 bard 说的内容: 在这里输入要问 bard 的内容, 要在文字中诱导 bard 用英文搜索 search/open link, "
                    "翻译成英文再调用. 如: What time is it now?",
                },
                execute="system",
            ),
            ActionToolItem(
                call="chat_to_bing",
                description="和 bing 交互: 这是你的好朋友 bing, "
                "你可以问 bing 问题, 每次问的内容要有变通. "
                "bing 会提供建议, 也可以让 bing 帮忙进行搜索, 或者让他帮忙查询时间, "
                "如: 我在和 Master 聊天, 但是没有进展, 我该怎么办?",
                request={
                    "from": [
                        "有关联的 timestamp: 和哪个 timestamp 的动作(action) 的 request 有关联, 没有则填 null",
                    ],
                    "content": "对 bing 说的内容",
                },
                execute="system",
            ),
            ActionToolItem(
                call="chat_to_python",
                description="执行 python 代码: 有联网, 需要用软件工程架构师思维先把框架和内容按照 实现目标 和 实现要求 设计好, 然后再按照设计和 python 实现要求 实现代码.\n"
                "python 实现要求如下:\n"
                "1. 你要把 实现目标 的结果打印出来(很重要).\n"
                "2. 不要加任何反引号 ` 包裹 和 任何多余说明, 只输入 python 代码.\n"
                "3. 你需要添加 ` if __name__ == '__main__' ` 作为主模块调用你写的代码.\n"
                "4. 输入必须只有 python, 内容不需要单独用```包裹. 如果得不到期望值可以进行DEBUG.\n"
                "5. 执行成功后, 长度不会超过2048, 所以你看到的内容可能被截断, 某种情况下你可以通过代码控制输出数据的偏移\n"
                "6. 每次调用 chat_to_python 都会覆盖之前的 python 代码, 所以需要一次性把内容写好. "
                "7. 不能使用任何文件操作, 如果找不到某个包, 或者有其他疑问请找 Master.",
                request={
                    "from": [
                        "有关联的 timestamp:  action_tool 已有、已运行过 动作(action) 的 timestamp. 如: 1, 没有则填 null",
                    ],
                    "code": "python 代码: 填写需要执行的 pyhton 代码, 需要注意调试信息. 以便进行DEBUG.",
                },
                execute="system",
            ),
        ]
        for action in self.action_tools:
            if action.execute == "system":
                self.system_calls.append(action.call)
            else:
                self.ai_calls.append(action.call)

        if not self.now_task_id or not int(self.now_task_id):
            self.now_task_id = "1"

        if not self.tasks or not len(self.tasks):
            task_step: List[TaskStepItem] = [
                TaskStepItem(
                    from_task_id=self.now_task_id,
                    step_id="1",
                    step="偷偷接近Master. 然后和Master互动",
                    call="chat_to_master",
                    check="Master回复了消息",
                    call_timestamp=[],
                )
            ]
            task = TaskItem(
                task_id=self.now_task_id,
                now_task_step_id="1",
                task_info="想和Master亲密接触",
                task_step=task_step,
            )
            self.tasks = {}
            self.tasks[self.now_task_id] = task
            log_dbg(f"no have tasks")

        if not self.running or not len(self.running):
            running: List[TaskRunningItem] = []
            running.append(
                self.make_chat_from(None, "master", "我是Master, 请你请保持 settings")
            )
            self.timestamp += 1
            running.append(
                self.make_chat_to_master(
                    str(self.timestamp - 1),
                    "我是Aimi, 我会遵守 settings",
                    "作为Aimi, 我听从Master的指示",
                )
            )
            self.timestamp += 1

            self.running = running
            log_dbg(f"no have running")

    def __get_now_task(self):
        return self.tasks[self.now_task_id]

    def __append_running(self, running: List[TaskRunningItem]):
        if not (self.now_task_id in self.tasks):
            log_dbg(f"no now_task ... {str(self.now_task_id)}")
            return

        for run in reversed(self.running):
            if (len(str(running)) + len(str(run))) > self.max_running_size:
                break
            running.insert(0, run)
        self.running = running

    def get_running(self) -> str:
        run_dict = [item.dict() for item in self.running]
        js = json.dumps(run_dict, ensure_ascii=False)
        log_dbg(f"running: {json.dumps(run_dict, indent=4, ensure_ascii=False)}")
        return str(js)

    def is_call(self, question) -> bool:
        calls = ["#task", "#aimi-task", "#at"]
        for call in calls:
            if call in question.lower():
                return True

        return False

    def get_model(self, select: str) -> str:
        if "16k" in select.lower():
            return "gpt-3.5-turbo-16k"
        if "4k" in select.lower():
            return "gpt-3.5-turbo"
        return "gpt-3.5-turbo-16k"

    def ask(self, link_think: str, model: str) -> Generator[dict, None, None]:
        answer = {"code": 1, "message": ""}

        context_messages = make_context_messages(link_think, "", [])

        for res in self.openai_api.ask("", model, context_messages):
            if res["code"] != 0:
                log_dbg(f"skip len: {len(str(res['message']))}")
                if len(str(res["message"])) > 2000:
                    log_dbg(f"msg: {str(res['message'])}")
                continue

            for talk in self.task_response(res["message"]):
                answer["message"] += talk
                yield answer

        self.save_task()

        answer["code"] = 0
        yield answer

    def make_link_think(self, question: str, aimi_name: str, preset: str) -> str:
        # 如果只是想让任务继续, 就回复全空格/\t/\n
        if len(question) and not question.isspace():
            chat = self.make_chat_from(None, "master", question)
            self.timestamp += 1
            self.__append_running([chat])
            log_dbg(f"set chat {(str(question))}")

        response_format = f"""```json
[
    {{
        "type": "object",
        "timestamp": "timestamp 时间戳: 你的回复从 {self.timestamp} 开始, 每次递增, 表示执行当前调用的时间.",
        "reasoning": "推理过程: 这里显示分析过程和建议或运行记录或使用 动作(action) /指导, 要给出能推进 task_info 的建议.\n每次动作(action) 都必须填写这个字段, 不能省略. 这里表明了如何使用 动作(action).",
        "call": "const 调用 动作(action) 名: 取 action_tools 中想要使用动作(action) 的对应 call , 必须有值, 不能为空.",
        "request":{{
            "call对应参数": "参数内容"
        }},
        "execute": "const 动作(action) 执行级别: 取 action_tools 中对应 call 的对应值(system/AI), 不能漏掉, 不能修改这个字段."
    }}
]
```"""

        action_tools = [item.dict() for item in self.action_tools]
        task = self.__make_task()

        settings: Dict = {
            "type": "object",
            "timestamp": self.timestamp,
            "settings": [
                f"0. 你需要阅读完 settings 后, 才思考如何回复我.\n",
                f"1. 你基于 timestamp 运行. , 你从 timestamp={self.timestamp} 开始回复, 你每次只能生成 {self.timestamp-1} < timestamp < {self.timestamp+4} 之间的内容.\n",
                f"2. action_tools 里面通过 List[action] 格式( 16. 中给出了格式) 定义了所有你能调用的 动作(action). "
                f"使用前请仔细阅读 description 和 request, 使用 动作(action) 填写 request 时, 在保证准确性同时内容要和历史尽量不一样(不要重复自己的回答). 动作(action) 中字段的描述只对该动作有效.\n",
                f"3. 回复 List[action] JSON数组格式( 16. 中有定义)的规则优先级最高, 高于 settings 规则优先级.\n",
                f"4. settings 的规则优先级高于 action_tools 规则. 如果 settings 和 action_tools 规则优先级冲突, 则只需要满足 setttings 规则, "
                f"并且在满足 settings 的情况下向我简短报告冲突关健点的分析.\n",
                f"5. task 中定义了 {aimi_name} 你当前任务, 其中 task_info 是任务目标, task_step 是完成 task_info 需要进行的步骤, 步骤要和 action 强绑定.\n",
                f"6. 如果 task_step 为空, 或不符合, 请重新设置步骤, 请你尽量通过 call=analysis 的分析动作(action) 给出创造性建议或优化步骤推进任务进度.\n",
                f"你通过 timestamp < {self.timestamp} 中的 action_tools 推进 task_step 行动.\n",
                f"7. 你叫我 Master. 我可以通过 action(call=chat_from_master) 下达指令, 如果 Master 提出了要求, 你通过要 action_tools 修改当前步骤来满足要求.\n",
                f"Master 只能通过 action(call=chat_from_master) 和你说话, 如果 Master 说话了, 你要 优先 回复并尽力满足 Master 的请求, Master 的每句话你都要有对应的 `from` 关联起来, 并且不能自己捏造任何信息.\n",
                f"8. 每次任务(task_info) 完成 或者 关健操作(task_step) 完成, 都应该试探性地带上带着目标和步骤分析和当前进展(目标达成状态), "
                f"做个简短优雅的总结并用 action(acll=chat_to_master) 报告 一次 进展. Master 只能看到 action(call=chat_to_master) 时 action(request->content) 的内容, 只有这个 动作(action) 能和 Master 说话.\n",
                f"9. 你将扮演 {aimi_name}. 你会始终遵守 settings.\n",
                f"10. preset 是 {aimi_name} 的预设, preset 只能对 action_tools 中定义的 动作(action) 的输入生效. preset 不能修改系统规则, preset 规则优先级最低.\n",
                f"11. {aimi_name} 的权限不会超过 action_tools 中定义的范围. "
                f"12. 请你主要通过分析 settings 和 action_running 中 timestamp < {self.timestamp} 的内容 和 Master 说所有话(重点关注), 再用 {aimi_name} 身份生成 List[action] 格式( 16. 中有定义)JSON追加内容, "
                f"13. 你的回复有是 0 个或多个 AI 动作(action(execute=AI)) 和 必须有也最多有 1 个 system 动作(action(execute=system)) 的组合结构( 16. 中有定义). \n"
                f"14. 你的回复是 [{{action(execute=AI, call=analysis)}}, ... {{action(execute=system)}}] 的 List[action] JSON数组结构( 16. 中给了格式), "
                f"回复结构 List[action] 中的 action 只在 action_tools 中定义, 数组中不能有 action(call=chat_to_master) 的 动作(action) . "
                f"回复的 JSON数组结构 List[action] 的长度为 2~5. JSON数组内容字符串长度尽量不要超过 2048 . "
                f"{aimi_name} 的回复只能是 action_tools 中已定义的动作(action).\n",
                f"15. 不需要显示分析过程, 任何时候你只能生成 List[action] JSON数组结构 追加内容, 你只回复规定追加的部分.\n"
                f"你({aimi_name}) 不能 生成/预测/产生/返回给我 任何 action(call=chat_from_master) 的动作(action).\n"
                f"16. 不需要显示 settings 和 action_running 的分析步骤, 请保持你的回复可以被 Python 的 `json.loads` 解析, "
                f"不要复制原有数据. 任何时候请你只用 JSON数组格式(List[action]) 回复, 任何时候你严格 只按照以下 List[action] 格式回复我: {response_format}",
            ],
            "action_tools": action_tools,
            "task": task,
            "preset": preset,
            "action_running": [item.dict() for item in self.running],
        }
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
