class fifo:
    def __init__(self, size=3):
        self._size = size
        self._count = 0
        self._data = []

    def add(self, elem):
        self._data.append(elem)
        if self._count > self._size:
            self._data.pop(0)
        else:
            self._count += 1

    def pop(self):
        if self._count > 0:
            self._count -= 1
            return self._data.pop(0)
        else:
            raise IndexError("Empty")

    def avg(self):
        if self._count > 0:
            return sum(self._data) / self._count
        return 0

    def __str__(self):
        return str(self._data)


if __name__ == '__main__':
    a = fifo()
    for i in range(200):
        a.add(i)
        print(a)
