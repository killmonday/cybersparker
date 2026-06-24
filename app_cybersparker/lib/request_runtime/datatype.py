from collections import OrderedDict


class AttribDict(OrderedDict):
    __exclude_keys__ = set()

    def __getattr__(self, name):
        if (
            name.startswith("__")
            or name.startswith("_OrderedDict__")
            or name in self.__exclude_keys__
        ):
            return super(AttribDict, self).__getattribute__(name)
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        if (
            name.startswith("__")
            or name.startswith("_OrderedDict__")
            or name in self.__exclude_keys__
        ):
            return super(AttribDict, self).__setattr__(name, value)
        self[name] = value

    def __delattr__(self, name):
        if (
            name.startswith("__")
            or name.startswith("_OrderedDict__")
            or name in self.__exclude_keys__
        ):
            return super(AttribDict, self).__delattr__(name)
        del self[name]
