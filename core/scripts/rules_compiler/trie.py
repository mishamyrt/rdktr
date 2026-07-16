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
        """Returns (base, check, wid, pfx) arrays. Slot 0 is the root."""
        size = 1024
        base = [0] * size
        check = [NONE] * size
        wid = [NONE] * size
        pfx = [NONE] * size

        def ensure(n: int) -> None:
            nonlocal size
            while size < n:
                size *= 2
            while len(base) < size:
                base.append(0)
                check.append(NONE)
                wid.append(NONE)
                pfx.append(NONE)

        slot_of = {0: 0}
        wid[0] = self.word_id[0]
        pfx[0] = self.prefix_id[0]
        search_hint = 1
        queue = [0]
        while queue:
            node = queue.pop(0)
            kids = self.children[node]
            if not kids:
                continue
            bytes_ = sorted(kids.keys())
            s = slot_of[node]
            b = max(1, search_hint - bytes_[0])
            while True:
                ensure(b + 256 + 1)
                if all(check[b + c] == NONE for c in bytes_):
                    break
                b += 1
            base[s] = b
            for c in bytes_:
                t = b + c
                child = kids[c]
                check[t] = s
                wid[t] = self.word_id[child]
                pfx[t] = self.prefix_id[child]
                slot_of[child] = t
                queue.append(child)
            # advance hint past fully occupied region
            while search_hint < size and check[search_hint] != NONE:
                search_hint += 1
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
