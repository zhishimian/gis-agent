from dataclasses import dataclass
from inspect import signature
from typing import Any,Callable
@dataclass
class Tool:
    name:str
    description:str
    parameters:dict
    function:Callable[...,Any]

    def schema(self):
        return {
            "type":"function",
            "function":{
                "name":self.name,
                "description":self.description,
                "parameters":self.parameters,
            },
        }
    def run(self,arguments):
        try:
            signature(self.function).bind(**arguments)
        except TypeError as error:
            return {"ok": False, "error": f"工具参数不匹配：{error}"}
        return self.function(**arguments)
