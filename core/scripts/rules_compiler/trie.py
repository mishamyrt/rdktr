"""Double-array trie shared by exact words and prefix stems."""

from .constants import NONE


class Trie:
    def __init__(self) -> None:
        self.children: list[dict[int, int]] = [{}]  # node -> {byte: node}
        self.word_id: list[int] = [NONE]
        self.prefix_id: list[int] = [NONE]

    def _walk_insert(self, key: bytes) -> int:
        node = 0
        for b in key:
            nxt = self.children[node].get(b)
            if nxt is None:
                nxt = len(self.children)
                self.children.append({})
                self.word_id.append(NONE)
                self.prefix_id.append(NONE)
                self.children[node][b] = nxt
            node = nxt
        return node

    def insert_word(self, word: str, wid: int) -> None:
        node = self._walk_insert(word.encode("utf-8"))
        assert self.word_id[node] in (NONE, wid)
        self.word_id[node] = wid

    def insert_prefix(self, prefix: str, pid: int) -> None:
        node = self._walk_insert(prefix.encode("utf-8"))
        assert self.prefix_id[node] in (NONE, pid)
        self.prefix_id[node] = pid

    def build_double_array(self) -> tuple[list[int], list[int], list[int], list[int]]:
        """Returns (base, check, wid, pfx) arrays. Slot 0 is the root.

        Free slots are kept in a doubly-linked list so the base search only
        probes free slots; a plain linear scan degrades quadratically here
        because multibyte UTF-8 leaves the low slots permanently free.
        """
        size = 1024
        base = [0] * size
        check = [NONE] * size
        wid = [NONE] * size
        pfx = [NONE] * size
        # free list over slots [1, size); `size` acts as the end sentinel,
        # prv of the head is -1
        nxt = list(range(1, size + 1))
        prv = list(range(-1, size - 1))
        head = 1
        prv[1] = -1
        tail = size - 1

        def grow() -> None:
            nonlocal size, head, tail
            old = size
            size *= 2
            base.extend([0] * old)
            check.extend([NONE] * old)
            wid.extend([NONE] * old)
            pfx.extend([NONE] * old)
            nxt.extend(range(old + 1, size + 1))
            prv.extend(range(old - 1, size - 1))
            if head == old:  # list was empty
                prv[old] = -1
            else:
                nxt[tail] = old
                prv[old] = tail
            tail = size - 1

        def occupy(t: int) -> None:
            nonlocal head, tail
            p, q = prv[t], nxt[t]
            if p == -1:
                head = q
            else:
                nxt[p] = q
            if q < size:
                prv[q] = p
            else:
                tail = p

        slot_of = {0: 0}
        wid[0] = self.word_id[0]
        pfx[0] = self.prefix_id[0]
        queue = [0]
        qi = 0
        while qi < len(queue):
            node = queue[qi]
            qi += 1
            kids = self.children[node]
            if not kids:
                continue
            bytes_ = sorted(kids.keys())
            first = bytes_[0]
            rest = bytes_[1:]
            s = slot_of[node]
            t = head
            while True:
                if t >= size:
                    grow()
                while size <= t + 256 + 1:
                    grow()
                b = t - first
                if b >= 1 and all(check[b + c] == NONE for c in rest):
                    break
                t = nxt[t]
            base[s] = b
            for c in bytes_:
                t = b + c
                child = kids[c]
                occupy(t)
                check[t] = s
                wid[t] = self.word_id[child]
                pfx[t] = self.prefix_id[child]
                slot_of[child] = t
                queue.append(child)
        used = max((i for i in range(size) if check[i] != NONE), default=0)
        n = used + 1
        return base[:n], check[:n], wid[:n], pfx[:n]

    @staticmethod
    def lookup(base: list[int], check: list[int], word: bytes) -> int | None:
        s = 0
        for b in word:
            t = base[s] + b
            if t >= len(check) or check[t] != s:
                return None
            s = t
        return s
