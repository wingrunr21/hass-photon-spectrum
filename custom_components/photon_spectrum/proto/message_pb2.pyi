from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SendTextMessageRequest(_message.Message):
    __slots__ = ("chat_guid", "text", "client_message_id")
    CHAT_GUID_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    CLIENT_MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    chat_guid: str
    text: str
    client_message_id: str
    def __init__(self, chat_guid: _Optional[str] = ..., text: _Optional[str] = ..., client_message_id: _Optional[str] = ...) -> None: ...

class Message(_message.Message):
    __slots__ = ("guid",)
    GUID_FIELD_NUMBER: _ClassVar[int]
    guid: str
    def __init__(self, guid: _Optional[str] = ...) -> None: ...

class MessageResponse(_message.Message):
    __slots__ = ("message",)
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    message: Message
    def __init__(self, message: _Optional[_Union[Message, _Mapping]] = ...) -> None: ...
