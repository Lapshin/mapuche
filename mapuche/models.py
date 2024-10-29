class MapValue:
    def __init__(self, name='Total', address=0, size=0, source='', diff=0, delta=0):
        self.name = name
        self.address = address
        self.size = size
        self.diff = diff
        self.delta = delta
        self.source = source

    def __repr__(self):
        return f'MapValue(name={self.name})'

    def get_tuple(self):
        return tuple([self.name, self.address, self.size, self.diff, self.delta])

    def value(self, value_id):
        return self.get_tuple()[value_id]


class TreeNode:
    def __init__(self, value, parent=None):
        self.value = value
        self.parent = parent
        self.level = parent.level + 1 if parent else 0
        self.hidden = False
        self.expand = False
        self.children = []
        self.sorted_id = -1
        self.sorted_reverse = False

    def add_child(self, value):
        child_node = TreeNode(value, self)
        self.children.append(child_node)
        return child_node

    def find_child_by_name(self, name):
        for c in self.children:
            if c.value.name == name:
                return c
        return None

    def is_last_child(self):
        return self.parent == None or self.parent.children[-1] == self

    def is_root(self):
        return self.parent == None

    def is_leaf(self):
        return len(self.children) == 0

    def remove_child_by_name(self, name):
        for c in self.children:
            if c.value.name == name:
                self.children.remove(c)

    def remove_children(self):
        self.children = []

    def set_expand(self, expand=None):
        if len(self.children):
            if expand != None:
                self.expand = expand
            else:
                self.expand = not self.expand

    def sort(self, sorted_id):
        if self.sorted_id != sorted_id:
            self.sorted_id = sorted_id
            self.sorted_reverse = False
        self.sorted_reverse = not self.sorted_reverse
        self.children.sort(reverse=self.sorted_reverse, key=lambda node: node.value.value(sorted_id))
        for c in self.children:
            c.sort(sorted_id);

    def get_ancestors(self):
        ancestors = []
        current_node = self.parent
        while current_node:
            ancestors.append(current_node.value)
            current_node = current_node.parent
        return ancestors

    def __repr__(self):
        return f'TreeNode(value={self.value})'
