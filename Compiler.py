from llvmlite import ir
import os

from AST import Expression, Program, Node, NodeType
from AST import ExpressionStatement, LetStatement, BlockStatement, ReturnStatement, FunctionStatement, AssignStatement 
from AST import IfStatement, WhileStatement, BreakStatement, ContinueStatement, ForStatement, ImportStatement
from AST import InfixExpression, CallExpression, PrefixExpression, PostfixExpression
from AST import IntegerLiteral, FloatLiteral, IdentifierLiteral, BooleanLiteral, StringLiteral
from AST import FunctionParameter

from Environment import Environment

from Lexer import Lexer
from Parser import Parser

class Compiler:
    def __init__(self):
        self.type_map: dict[str, ir.Type] = {
            'int': ir.IntType(32),
            'float': ir.FloatType(),
            'bool': ir.IntType(1),
            'str': ir.PointerType(ir.IntType(8)),
            'void': ir.VoidType(),
            'bb': ir.IntType(32),
            'des': ir.FloatType(),
            'teks': ir.PointerType(ir.IntType(8))
        }

        self.module: ir.Module = ir.Module('main')

        self.builder: ir.IRBuilder = ir.IRBuilder()

        self.env: Environment = Environment()

        self.errors: list[str] = []

        self.counter: int = 0

        # Initialize builtin functions
        self.__initialize_builtins()

        self.breakpoints: list[ir.Block] = []
        self.continues: list[ir.Block] = []

        # Reference to parsed pallets
        self.global_parsed_packages: dict[str, Program] = {}

    def __initialize_builtins(self) -> None:
        def __init_booleans() -> tuple[ir.GlobalVariable, ir.GlobalVariable]:
            bool_type: ir.Type = self.type_map['bool']

            true_var = ir.GlobalVariable(self.module, bool_type, 'true')
            true_var.initializer = ir.Constant(bool_type, 1)
            true_var.global_constant = True

            false_var = ir.GlobalVariable(self.module, bool_type, 'false')
            false_var.initializer = ir.Constant(bool_type, 0)
            false_var.global_constant = True

            return true_var, false_var
        
        # init print
        print_ty = ir.FunctionType(self.type_map['int'], [ir.IntType(8).as_pointer()], var_arg=True)
        print_fn = ir.Function(self.module, print_ty, 'printf')
        self.env.define('print', print_fn, ir.IntType(32))

        # Init fgets
        fgets_ty = ir.FunctionType(ir.IntType(8).as_pointer(), [ir.IntType(8).as_pointer(), ir.IntType(32), ir.IntType(8).as_pointer()])
        fgets_fn = ir.Function(self.module, fgets_ty, 'fgets')
        self.env.define('fgets', fgets_fn, ir.IntType(8).as_pointer())

        # init sscanf
        sscanf_ty = ir.FunctionType(ir.IntType(32), 
                                    [ir.IntType(8).as_pointer(), ir.IntType(8).as_pointer()],
                                    var_arg=True)
        sscanf_fn = ir.Function(self.module, sscanf_ty, 'sscanf')
        self.env.define('sscanf', sscanf_fn, ir.IntType(32))

        # init strlen
        strlen_ty = ir.FunctionType(ir.IntType(64), [ir.IntType(8).as_pointer()])
        strlen_fn = ir.Function(self.module, strlen_ty, 'strlen')
        self.env.define('strlen', strlen_fn, ir.IntType(64))

        # stdin
        stdin_var = ir.GlobalVariable(self.module, ir.IntType(8).as_pointer(), 'stdin')
        stdin_var.linkage = 'external'

        # init function input(), int(), float()
        self.env.define('input', None, ir.IntType(8).as_pointer())
        self.env.define('int', None, ir.IntType(32))
        self.env.define('float', None, ir.FloatType())

        true_var, false_var = __init_booleans()
        self.env.define('true', true_var, true_var.type)
        self.env.define('false', false_var, false_var.type)

    def __increment_counter(self) -> int:
        self.counter += 1
        return self.counter

    def compile(self, node: Node) -> None:
        match node.type():
            case NodeType.Program:
                self.__visit_program(node)

            # Statement
            case NodeType.ExpressionStatement:
                self.__visit_expression_statement(node)
            case NodeType.LetStatement:
                self.__visit_let_statement(node)
            case NodeType.FunctionStatement:
                self.__visit_function_statement(node)
            case NodeType.AssignStatement:
                self.__visit_assign_statement(node)
            case NodeType.BlockStatement:
                self.__visit_block_statement(node)
            case NodeType.ReturnStatement:
                self.__visit_return_statement(node)
            case NodeType.IfStatement:
                self.__visit_if_statement(node)
            case NodeType.WhileStatement:
                self.__visit_while_statement(node)
            case NodeType.BreakStatement:
                self.__visit_break_statement(node)
            case NodeType.ContinueStatement:
                self.__visit_continue_statement(node)
            case NodeType.ForStatement:
                self.__visit_for_statement(node)
            case NodeType.ImportStatement:
                self.__visit_import_statement(node)

            # Expression
            case NodeType.InfixExpression:
                self.__visit_infix_expression(node)
            case NodeType.CallExpression:
                self.__visit_call_expression(node)
            case NodeType.PostfixExpression:
                self.__visit_postfix_expression(node)

    # region visit method
    def __visit_program(self, node: Program) -> None:
        for stmt in node.statements:
            self.compile(stmt)

    # region Statements
    def __visit_expression_statement(self, node: ExpressionStatement) -> None:
        self.compile(node.expr)
    
    def __visit_let_statement(self, node: LetStatement) -> None:
        name: str = node.name.value
        value: Expression = node.value

        value, Type = self.__resolve_value(node=value)

        if self.env.lookup(name) is None:
            # Allocate the variable
            ptr = self.builder.alloca(Type)

            # Store the value to ptr
            self.builder.store(value, ptr)

            # Add the variable to environment
            self.env.define(name, ptr, Type)
        else:
            ptr, _ = self.env.lookup(name)
            self.builder.store(value, ptr)

    def __visit_block_statement(self, node: BlockStatement) -> None:
        for stmt in node.statements:
            self.compile(stmt)

    def __visit_return_statement(self, node: ReturnStatement) -> None:
        func_return_type = self.builder.function.ftype.return_type

        if isinstance(func_return_type, ir.VoidType) or node.return_value is None:
            self.builder.ret_void()
            return

        value: Expression = node.return_value
        value, Type = self.__resolve_value(value)
        self.builder.ret(value)

    def __visit_function_statement(self, node: FunctionStatement) -> None:
        name: str = node.name.value
        body: BlockStatement = node.body
        params: list[FunctionParameter] = node.parameters

        # Keep the names of each parameters
        param_names: list[str] = [p.name for p in params]

        # Keep track of types for each parameters
        param_types: list[ir.Type] = [self.type_map[p.value_type] for p in params]

        return_type: ir.Type = self.type_map[node.return_type]

        fnty: ir.FunctionType = ir.FunctionType(return_type, param_types)
        func: ir.Function = ir.Function(self.module, fnty, name=name)

        block: ir.Block = func.append_basic_block(f'{name}_entry')

        previous_builder = self.builder

        self.builder = ir.IRBuilder(block)

        params_ptr = []
        for i, typ in enumerate(param_types):
            ptr = self.builder.alloca(typ)
            self.builder.store(func.args[i], ptr)
            params_ptr.append(ptr)

        previous_env = self.env
        self.env = Environment(parent=previous_env)
        for i, x in enumerate(zip(param_types, param_names)):
            typ = param_types[i]
            ptr = params_ptr[i]

            self.env.define(x[1], ptr, typ)

        self.env.define(name, func, return_type)

        self.compile(body)

        if not self.builder.block.is_terminated:
            if isinstance(return_type, ir.VoidType):
                self.builder.ret_void()
            elif isinstance(return_type, ir.FloatType):
                self.builder.ret(ir.Constant(ir.FloatType(), 0.0))
            else:
                self.builder.ret(ir.Constant(ir.IntType(32), 0))

        self.env = previous_env
        self.env.define(name, func, return_type)
        self.builder = previous_builder

    def __visit_assign_statement(self, node: AssignStatement) -> None:
        name: str = node.ident.value
        operator: str = node.operator
        value: Expression = node.right_value

        if self.env.lookup(name) is None:
            self.errors.append(f"COMPILE ERROR: Identifier {name} doesn't exist")
            return

        right_value, right_type = self.__resolve_value(node=value)
        
        var_ptr, _ = self.env.lookup(name)
        ori_value = self.builder.load(var_ptr)

        if isinstance(ori_value.type, ir.IntType) and isinstance(right_type, ir.FloatType):
            right_value = self.builder.fptosi(right_value, ir.IntType(32))
            right_type = ir.IntType(32)
        if isinstance(ori_value.type, ir.FloatType) and isinstance(right_type, ir.IntType):
            right_value = self.builder.sitofp(right_value, ir.FloatType())
            right_type = ir.FloatType()

        value, Type = None, None
        match operator:
            case '=':
                value = right_value
            case '+=':
                if isinstance(ori_value.type, ir.IntType) and isinstance(right_type, ir.IntType):
                    value = self.builder.add(ori_value, right_value)
                else:
                    value = self.builder.fadd(ori_value, right_value)
            case '-=':
                if isinstance(ori_value.type, ir.IntType) and isinstance(right_type, ir.IntType):
                    value = self.builder.sub(ori_value, right_value)
                else:
                    value = self.builder.fsub(ori_value, right_value)
            case '*=':
                if isinstance(ori_value.type, ir.IntType) and isinstance(right_type, ir.IntType):
                    value = self.builder.mul(ori_value, right_value)
                else:
                    value = self.builder.fmul(ori_value, right_value)
            case '/=':
                if isinstance(ori_value.type, ir.IntType) and isinstance(right_type, ir.IntType):
                    value = self.builder.sdiv(ori_value, right_value)
                else:
                    value = self.builder.fdiv(ori_value, right_value)
            case '%=':
                if isinstance(ori_value.type, ir.IntType) and isinstance(right_type, ir.IntType):
                    value = self.builder.srem(ori_value, right_value)
                else:
                    value = self.builder.frem(ori_value, right_value)
            case _:
                print("Unsupported Assignment Operator")

        ptr, _ = self.env.lookup(name)
        self.builder.store(value, ptr)

    def __visit_if_statement(self, node: IfStatement) -> None:
        condition = node.condition
        consequence = node.consequence
        alternative = node.alternative

        test, _ = self.__resolve_value(condition)

        if alternative is None:
            with self.builder.if_then(test):
                self.compile(consequence)
        else:
            with self.builder.if_else(test) as (true, otherwise):
                with true:
                    self.compile(consequence)
                with otherwise:
                    self.compile(alternative)

    def __visit_while_statement(self, node: WhileStatement) -> None:
        condition: Expression = node.condition
        body: BlockStatement = node.body

        # TODO implement save/restore env variables

        test, _ = self.__resolve_value(condition)

        while_loop_entry = self.builder.append_basic_block(f"while_loop_entry_{self.__increment_counter()}")

        while_loop_otherwise = self.builder.append_basic_block(f"while_loop_otherwise_{self.counter}")

        self.builder.cbranch(test, while_loop_entry, while_loop_otherwise)
        self.builder.position_at_start(while_loop_entry)
        self.compile(body)

        test, _ = self.__resolve_value(condition)
        self.builder.cbranch(test, while_loop_entry, while_loop_otherwise)
        self.builder.position_at_start(while_loop_otherwise)

    def __visit_break_statement(self, node: BreakStatement) -> None:
        self.builder.branch(self.breakpoints[-1])

    def __visit_continue_statement(self, node: ContinueStatement) -> None:
        self.builder.branch(self.continues[-1])

    def __visit_for_statement(self, node: ForStatement) -> None:
        var_declaration: LetStatement = node.var_declaration
        condition: Expression = node.condition
        action: AssignStatement = node.action
        body: BlockStatement = node.body

        previous_env = self.env
        self.env = Environment(parent=previous_env)

        self.compile(var_declaration)

        counter = self.__increment_counter()
        for_loop_cond = self.builder.append_basic_block(f"for_loop_cond_{counter}")
        for_loop_body = self.builder.append_basic_block(f"for_loop_body_{counter}")
        for_loop_increment = self.builder.append_basic_block(f"for_loop_increment_{counter}")
        for_loop_end = self.builder.append_basic_block(f"for_loop_end_{counter}")

        self.breakpoints.append(for_loop_end)
        self.continues.append(for_loop_increment)

        # Check Condition after continues
        self.builder.branch(for_loop_cond)

        # Condition block
        self.builder.position_at_start(for_loop_cond)
        test, _ = self.__resolve_value(condition)
        self.builder.cbranch(test, for_loop_body, for_loop_end)

        self.builder.position_at_start(for_loop_body)
        self.compile(body)
        if not self.builder.block.is_terminated:
            self.builder.branch(for_loop_increment)

        self.builder.position_at_start(for_loop_increment)
        self.compile(action)
        self.builder.branch(for_loop_cond)  # loop back to condition

        # -- End block --
        self.builder.position_at_start(for_loop_end)

        self.breakpoints.pop()
        self.continues.pop()

        self.env = previous_env

    def __visit_import_statement(self, node: ImportStatement) -> None:
        file_path: str = node.file_path

        if self.global_parsed_packages.get(file_path) is not None:
            # REMINDER change to bahasa
            print(f"[warning]: `{file_path}` is already imported\n")
            return
        
        with open(os.path.abspath(f"{file_path}"), "r") as f:
            package_code: str = f.read()

        l: Lexer = Lexer(source=package_code)
        p: Parser = Parser(lexer=l)

        program: Program = p.parse_program()
        if len(p.errors) > 0:
            print(f"Error with imported package: {file_path}")
            for err in p.errors:
                print(err)
            exit(1)

        self.compile(node=program)

        self.global_parsed_packages[file_path] = program
    # endregion

    # region Expression
    def __visit_infix_expression(self, node: InfixExpression) -> None:
        operator: str = node.operator
        left_value, left_type = self.__resolve_value(node.left_node)
        right_value, right_type = self.__resolve_value(node.right_node)

        value = None
        Type = None
        if isinstance(right_type, ir.IntType) and isinstance(left_type, ir.IntType):
            Type = self.type_map['int']
            match operator:
                case '+':
                    value = self.builder.add(left_value, right_value)
                case '-':
                    value = self.builder.sub(left_value, right_value)
                case '*':
                    value = self.builder.mul(left_value, right_value)
                case '/':
                    value = self.builder.sdiv(left_value, right_value)
                case '%':
                    value = self.builder.srem(left_value, right_value)
                case '^':
                    # TODO
                    pass
                case '<':
                    value = self.builder.icmp_signed('<', left_value, right_value)
                    Type = ir.IntType(1)
                case '<=':
                    value = self.builder.icmp_signed('<=', left_value, right_value)
                    Type = ir.IntType(1)
                case '>':
                    value = self.builder.icmp_signed('>', left_value, right_value)
                    Type = ir.IntType(1)
                case '>=':
                    value = self.builder.icmp_signed('>=', left_value, right_value)
                    Type = ir.IntType(1)
                case '==':
                    value = self.builder.icmp_signed('==', left_value, right_value)
                    Type = ir.IntType(1)
                case '!=':
                    value = self.builder.icmp_signed('!=', left_value, right_value)
                    Type = ir.IntType(1)
        elif isinstance(right_type, ir.FloatType) and isinstance(left_type, ir.FloatType):
            Type = self.type_map['float']
            match operator:
                case '+':
                    value = self.builder.fadd(left_value, right_value)
                case '-':
                    value = self.builder.fsub(left_value, right_value)
                case '*':
                    value = self.builder.fmul(left_value, right_value)
                case '/':
                    value = self.builder.fdiv(left_value, right_value)
                case '%':
                    value = self.builder.frem(left_value, right_value)
                case '^':
                    # TODO
                    pass
                case '<':
                    value = self.builder.fcmp_ordered('<', left_value, right_value)
                    Type = ir.IntType(1)
                case '<=':
                    value = self.builder.fcmp_ordered('<=', left_value, right_value)
                    Type = ir.IntType(1)
                case '>':
                    value = self.builder.fcmp_ordered('>', left_value, right_value)
                    Type = ir.IntType(1)
                case '>=':
                    value = self.builder.fcmp_ordered('>=', left_value, right_value)
                    Type = ir.IntType(1)
                case '==':
                    value = self.builder.fcmp_ordered('==', left_value, right_value)
                    Type = ir.IntType(1)
                case '!=':
                    value = self.builder.fcmp_ordered('!=', left_value, right_value)
                    Type = ir.IntType(1)

        return value, Type
    
    def __visit_call_expression(self, node: CallExpression) -> tuple[ir.Instruction, ir.Type]:
        name: str = node.function.value
        params: list[Expression] = node.arguments

        args = []
        types = []
        if len(params) > 0:
            for x in params:
                p_val, p_type = self.__resolve_value(x)
                args.append(p_val)
                types.append(p_type)

        match name:
            # TODO Change to 'cetak'
            case 'print':
                ret = self.builtin_print(params=args, return_type=types)
                ret_type = self.type_map['int']
            case 'input':
                ret, ret_type = self.builtin_input(params=args)
            case 'int':
                ret, ret_type = self.builtin_int(params=args, param_types=types)
            case 'float':
                ret, ret_type = self.builtin_float(params=args, param_types=types)
            case _:
                func, ret_type = self.env.lookup(name)
                ret = self.builder.call(func, args)

                if isinstance(ret_type, ir.VoidType):
                    return None, ir.VoidType()

        return ret, ret_type
    
    def __visit_prefix_expression(self, node: PrefixExpression) -> tuple[ir.Value, ir.Type]:
        operator: str = node.operator
        right_node: Expression = node.right_node

        right_value, right_type = self.__resolve_value(right_node)

        Type, value = None, None

        if isinstance(right_type, ir.FloatType):
            Type = ir.FloatType()
            match operator:
                case '-':
                    value = self.builder.fmul(right_value, ir.Constant(ir.FloatType(), -1.0))
                case '!':
                    value = ir.Constant(ir.IntType(1), 0)
        elif isinstance(right_type, ir.IntType):
            Type = ir.IntType(32)
            match operator:
                case '-':
                    value = self.builder.mul(right_value, ir.Constant(ir.IntType(32), -1))
                case '!':
                    value = self.builder.not_(right_value)
        
        return value, Type
    
    def __visit_postfix_expression(self, node: PostfixExpression) -> None:
        left_node: IdentifierLiteral = node.left_node
        operator: str = node.operator

        if self.env.lookup(left_node.value) is None:
            # REMINDER change to bahasa
            self.errors.append(f"COMPILE ERROR: Identifier {left_node.value} has not been declared before")
            return
        
        var_ptr, _ = self.env.lookup(left_node.value)
        ori_value = self.builder.load(var_ptr)

        value = None

        match operator:
            case "++":
                if isinstance(ori_value.type,ir.IntType):
                    value = self.builder.add(ori_value, ir.Constant(ir.IntType(32), 1))
                elif isinstance(ori_value.type, ir.FloatType):
                    value = self.builder.fadd(ori_value, ir.Constant(ir.FloatType(), 1.0))
            case "--":
                if isinstance(ori_value.type,ir.IntType):
                    value = self.builder.sub(ori_value, ir.Constant(ir.IntType(32), 1))
                elif isinstance(ori_value.type, ir.FloatType):
                    value = self.builder.fsub(ori_value, ir.Constant(ir.FloatType(), 1.0))
        
        self.builder.store(value, var_ptr)
    # endregion

    # endregion

    # region Helpers Method
    def __resolve_value(self, node: Expression) -> tuple[ir.Value, ir.Type]:
        match node.type():
            case NodeType.IntegerLiteral:
                node: IntegerLiteral = node
                value, Type = node.value, self.type_map['int']
                return ir.Constant(Type, value), Type
            case NodeType.FloatLiteral:
                node: FloatLiteral = node
                value, Type = node.value, self.type_map['float']
                return ir.Constant(Type, value), Type
            case NodeType.IdentifierLiteral:
                node: IdentifierLiteral = node
                ptr, Type = self.env.lookup(node.value)
                return self.builder.load(ptr), Type
            case NodeType.BooleanLiteral:
                node: BooleanLiteral = node
                return ir.Constant(ir.IntType(1), 1 if node.value else 0), ir.IntType(1)
            case NodeType.StringLiteral:
                node: StringLiteral = node
                string, Type = self.__convert_string(node.value)
                return string, Type

            # Expression Value
            case NodeType.InfixExpression:
                return self.__visit_infix_expression(node)
            case NodeType.CallExpression:
                result, ret_type = self.__visit_call_expression(node)
                if result is None:
                    return None, ir.VoidType()
                return result, ret_type
            case NodeType.PrefixExpression:
                return self.__visit_prefix_expression(node)
            
    def __convert_string(self, string: str) -> tuple[ir.Constant, ir.ArrayType]:
        string = string.replace("\\n", "\n\0")

        fmt: str = f"{string}\0"
        c_fmt: ir.Constant = ir.Constant(ir.ArrayType(ir.IntType(8), len(fmt)), bytearray(fmt.encode("utf8")))

        global_fmt = ir.GlobalVariable(self.module, c_fmt.type, name=f'__str_{self.__increment_counter()}')
        global_fmt.linkage = 'internal'
        global_fmt.global_constant = True
        global_fmt.initializer = c_fmt

        return global_fmt, global_fmt.type

    def __get_string_ptr(self, param) -> ir.Value:
        if isinstance(param, ir.LoadInstr):
            gv = param.operands[0]
            return self.builder.bitcast(gv, ir.IntType(8).as_pointer())
        return self.builder.bitcast(param, ir.IntType(8).as_pointer())

    def builtin_print(self, params: list[ir.Instruction], return_type: ir.Type) -> None:
        func, _ = self.env.lookup('print')
        
        fmt_parts = []
        fixed_args = []

        for param, p_type in zip(params, return_type):
            if isinstance(p_type, ir.PointerType) or isinstance(p_type, ir.ArrayType):
                if isinstance(param, ir.LoadInstr):
                    g_val_ptr = param.operands[0]
                    string_val = self.builder.load(g_val_ptr)
                    arg = self.builder.bitcast(string_val, ir.IntType(8).as_pointer())
                elif isinstance(param.type, ir.ArrayType):
                    arg = self.builder.bitcast(self.module.get_global(f"__str_{self.counter}"), ir.IntType(8).as_pointer())
                else:
                    arg = param
                fmt_parts.append("%s")
                fixed_args.append(arg)
            elif isinstance(p_type, ir.IntType):
                if p_type.width == 1:
                    fmt_parts.append("%d")
                    fixed_args.append(self.builder.zext(param, ir.IntType(32)))
                else:
                    fmt_parts.append("%d")
                    fixed_args.append(param)
            elif isinstance(p_type, ir.FloatType):
                fmt_parts.append("%f")
                fixed_args.append(self.builder.fpext(param, ir.DoubleType()))
            elif isinstance(p_type, ir.DoubleType):
                fmt_parts.append("%f")
                fixed_args.append(param)
            else:
                fmt_parts.append("%p")
                fixed_args.append(param)

        fmt_str = " ".join(fmt_parts) + "\n\0"
        c_fmt = ir.Constant(ir.ArrayType(ir.IntType(8), len(fmt_str)), bytearray(fmt_str.encode("utf8")))
        global_fmt = ir.GlobalVariable(self.module, c_fmt.type, name=f"__auto_fmt_{self.__increment_counter()}")
        global_fmt.linkage = 'internal'
        global_fmt.global_constant = True
        global_fmt.initializer = c_fmt

        fmt_arg = self.builder.bitcast(global_fmt, ir.IntType(8).as_pointer())
        return self.builder.call(func, [fmt_arg, *fixed_args])
    
    def builtin_input(self, params: list) -> tuple:
        printf_func, _ = self.env.lookup('print')
        fgets_func, _ = self.env.lookup('fgets')
        strlen_func, _ = self.env.lookup('strlen')

        # If print function in input
        if params:
            prompt_ptr = self.__get_string_ptr(params[0])
            fmt_s = "%s\0"
            c_fmt = ir.Constant(ir.ArrayType(ir.IntType(8), len(fmt_s)),
                                bytearray(fmt_s.encode()))
            gfmt = ir.GlobalVariable(self.module, c_fmt.type, name=f'__input_pfmt_{self.__increment_counter()}')
            gfmt.linkage = 'internal'
            gfmt.global_constant = True
            gfmt.initializer = c_fmt
            fmt_arg = self.builder.bitcast(gfmt, ir.IntType(8).as_pointer())
            self.builder.call(printf_func, [fmt_arg, prompt_ptr])

        # Allocate buffer
        buf_type = ir.ArrayType(ir.IntType(8), 256)
        buf = self.builder.alloca(buf_type, name='input_buf')
        buf_ptr = self.builder.bitcast(buf, ir.IntType(8).as_pointer())

        # fgets(buf, 256, stdin)
        stdin_global = self.module.get_global('stdin')
        stdin_val = self.builder.load(stdin_global)
        self.builder.call(fgets_func, [buf_ptr, ir.Constant(ir.IntType(32), 256), stdin_val])

        # strip '\n'
        str_len = self.builder.call(strlen_func, [buf_ptr])
        last_idx = self.builder.sub(str_len, ir.Constant(ir.IntType(64), 1))
        last_ptr = self.builder.gep(buf_ptr, [last_idx], inbounds=True)
        self.builder.store(ir.Constant(ir.IntType(8), 0), last_ptr)

        return buf_ptr, ir.IntType(8).as_pointer()
    
    def builtin_int(self, params: list, param_types: list) -> tuple:
        sscanf_func, _ = self.env.lookup('sscanf')

        src_type = param_types[0]
        src_val = params[0]

        if isinstance(src_type, ir.IntType) and src_type.width == 32:
            return src_val, ir.IntType(32)
        
        if isinstance(src_type, ir.FloatType):
            return self.builder.fptosi(src_val, ir.IntType(32)), ir.IntType(32)
        
        # str -> int
        fmt = "%d\0"
        c_fmt = ir.Constant(ir.ArrayType(ir.IntType(8), len(fmt)), bytearray(fmt.encode()))
        gfmt = ir.GlobalVariable(self.module, c_fmt.type, name=f'__int_fmt_{self.__increment_counter()}')
        gfmt.linkage = 'internal'
        gfmt.global_constant = True
        gfmt.initializer = c_fmt

        fmt_ptr = self.builder.bitcast(gfmt, ir.IntType(8).as_pointer())
        result_ptr = self.builder.alloca(ir.IntType(32), name='parsed_int')
        self.builder.call(sscanf_func, [src_val, fmt_ptr, result_ptr])
        return self.builder.load(result_ptr), ir.IntType(32)
    
    def builtin_float(self, params: list, param_types: list) -> tuple:
        sscanf_func, _ = self.env.lookup('sscanf')

        src_type = param_types[0]
        src_val = params[0]

        if isinstance(src_type, ir.FloatType):
            return src_val, ir.FloatType()
        
        if isinstance(src_type, ir.IntType):
            return self.builder.sitofp(src_val, ir.FloatType), ir.FloatType()
        
        # str -> int
        fmt = "%d\0"
        c_fmt = ir.Constant(ir.ArrayType(ir.IntType(8), len(fmt)), bytearray(fmt.encode()))
        gfmt = ir.GlobalVariable(self.module, c_fmt.type, name=f'__float_fmt_{self.__increment_counter()}')
        gfmt.linkage = 'internal'
        gfmt.global_constant = True
        gfmt.initializer = c_fmt

        fmt_ptr = self.builder.bitcast(gfmt, ir.IntType(8).as_pointer())
        result_ptr = self.builder.alloca(ir.DoubleType(), name='parsed_double')
        self.builder.call(sscanf_func, [src_val, fmt_ptr, result_ptr])
        double_val = self.builder.load(result_ptr)
        return self.builder.fptrunc(double_val, ir.FloatType()), ir.FloatType()
    # endregion