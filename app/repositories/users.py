from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_email(self, email: str) -> User | None:
        statement = select(User).where(User.email == email)
        return self.session.scalar(statement)

    def get_or_create(self, *, email: str, name: str) -> User:
        user = self.get_by_email(email)
        if user is not None:
            if user.name != name:
                user.name = name
            return user

        user = User(email=email, name=name)
        self.session.add(user)
        self.session.flush()
        return user
