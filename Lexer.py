from Token import Token, TokenType, lookup_ident
from typing import Any

class Lexer:
    def __init__(self, source: str) -> None:
        self.source = source

        self.position: int = -1
        self.read_position: int = 0
        self.line_no: int = 1

        self.current_char: str | None = None

        self.__read_char()

    def __read_char(self) -> None:
        self.current_char = self.__peek_char()
        self.position = self.read_position
        self.read_position += 1

    def __peek_char(self) -> str | None:
        if self.read_position >= len(self.source):
            return None
        
        return self.source[self.read_position]

    def __skip_whitespace(self) -> None:
        while self.current_char is not None and self.current_char.isspace():
            if self.current_char in ('\n', '\r'):
                self.line_no += 1

            self.__read_char()

    def __new_token(self, tt: TokenType, literal: Any) -> Token:
        return Token(type=tt,
                     literal=literal,
                     line_no=self.line_no,
                     position=self.position)

    def __is_digit(self, ch: str | None) -> bool:
        return ch is not None and '0' <= ch <= '9'

    def __is_letter(self, ch: str | None) -> bool:
        return ch is not None and ('a' <= ch <= 'z' or 'A' <= ch <= 'Z' or ch == '_')
    
    def __read_number(self) -> Token:
        start_pos: int = self.position
        dot_cnt: int = 0

        output: str = ""
        while self.__is_digit(self.current_char) or self.current_char == '.':
            if self.current_char == '.':
                dot_cnt += 1

            if dot_cnt > 1:
                print(f"Terlalu banyak desimal di angka pada baris {self.line_no}, posisi {self.position}")
                return self.__new_token(TokenType.ILLEGAL, self.source[start_pos:self.position])
            
            output += self.source[self.position]
            self.__read_char()

            if self.current_char is None:
                break

        if dot_cnt == 0:
            return self.__new_token(TokenType.INT, int(output))
        else:
            return self.__new_token(TokenType.FLOAT, float(output))
        
    def __read_identifier(self) -> str:
        position = self.position
        while self.current_char is not None and (self.__is_letter(self.current_char) or self.current_char.isalnum()):
            self.__read_char()
        return self.source[position:self.position]

    def next_token(self) -> Token:
        tok: Token
        
        self.__skip_whitespace()

        match self.current_char:
            case '+':
                if self.__peek_char() == "=":
                    ch = self.current_char
                    self.__read_char()
                    tok = self.__new_token(TokenType.PLUS_EQ, ch + self.current_char)
                elif self.__peek_char() == "+":
                    ch = self.current_char
                    self.__read_char()
                    tok = self.__new_token(TokenType.PLUS_PLUS, ch + self.current_char)    
                else:
                    tok = self.__new_token(TokenType.PLUS, self.current_char)
            case '-':
                # handle ->
                if self.__peek_char() == '>':
                    ch = self.current_char
                    self.__read_char()
                    tok = self.__new_token(TokenType.ARROW, ch + self.current_char)
                elif self.__peek_char() == '=':
                    ch = self.current_char
                    self.__read_char()
                    tok = self.__new_token(TokenType.MINUS_EQ, ch + self.current_char)
                elif self.__peek_char() == "-":
                    ch = self.current_char
                    self.__read_char()
                    tok = self.__new_token(TokenType.MINUS_MINUS, ch + self.current_char)
                else:
                    tok = self.__new_token(TokenType.MINUS, self.current_char)
            case '*':
                if self.__peek_char() == '=':
                    ch = self.current_char
                    self.__read_char()
                    tok = self.__new_token(TokenType.MUL_EQ, ch + self.current_char)
                else:
                    tok = self.__new_token(TokenType.ASTERISK, self.current_char)
            case '/':
                if self.__peek_char() == '=':
                    ch = self.current_char
                    self.__read_char()
                    tok = self.__new_token(TokenType.DIV_EQ, ch + self.current_char)
                else:
                    tok = self.__new_token(TokenType.SLASH, self.current_char)
            case '%':
                if self.__peek_char() == '=':
                    ch = self.current_char
                    self.__read_char()
                    tok = self.__new_token(TokenType.MOD_EQ, ch + self.current_char)
                else:
                    tok = self.__new_token(TokenType.MODULUS, self.current_char)
            case '<':
                if self.__peek_char() == '=':
                    ch = self.current_char
                    self.__read_char()
                    tok = self.__new_token(TokenType.LT_EQ, ch + self.current_char)
                else:
                    tok = self.__new_token(TokenType.LT, self.current_char)
            case '>':
                if self.__peek_char() == '=':
                    ch = self.current_char
                    self.__read_char()
                    tok = self.__new_token(TokenType.GT_EQ, ch + self.current_char)
                else:
                    tok = self.__new_token(TokenType.GT, self.current_char)
            case '=':
                if self.__peek_char() == '=':
                    ch = self.current_char
                    self.__read_char()
                    tok = self.__new_token(TokenType.EQ_EQ, ch + self.current_char)
                else:
                    tok = self.__new_token(TokenType.EQ, self.current_char)
            case '!':
                if self.__peek_char() == '=':
                    ch = self.current_char
                    self.__read_char()
                    tok = self.__new_token(TokenType.NOT_EQ, ch + self.current_char)
                else:
                    tok = self.__new_token(TokenType.BANG, self.current_char)
            case '^':
                tok = self.__new_token(TokenType.POW, self.current_char)
            case ':':
                tok = self.__new_token(TokenType.COLON, self.current_char)
            case ',':
                tok = self.__new_token(TokenType.COMMA, self.current_char)
            case '"':
                tok = self.__new_token(TokenType.STRING, self.__read_string())
            case '(':
                tok = self.__new_token(TokenType.LPAREN, self.current_char)
            case ')':
                tok = self.__new_token(TokenType.RPAREN, self.current_char)
            case '{':
                tok = self.__new_token(TokenType.LBRACE, self.current_char)
            case '}':
                tok = self.__new_token(TokenType.RBRACE, self.current_char)
            case ";":
                tok = self.__new_token(TokenType.SEMICOLON, self.current_char)
            case None:
                tok = self.__new_token(TokenType.EOF, "")
            case _:
                if self.__is_letter(self.current_char):
                    literal: str = self.__read_identifier()
                    tt: TokenType = lookup_ident(literal)
                    tok = self.__new_token(tt=tt, literal=literal)
                    return tok
                elif self.__is_digit(self.current_char):
                    tok = self.__read_number()
                    return tok
                else:
                    tok = self.__new_token(TokenType.ILLEGAL, self.current_char)

        self.__read_char()
        return tok
    
    def __read_string(self) -> str:
        position: int = self.position + 1
        while True:
            self.__read_char()
            if self.current_char == '"' or self.current_char is None:
                break
        return self.source[position:self.position]
