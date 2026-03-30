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

    def get_by_external_auth_id(self, external_auth_id: str) -> User | None:
        statement = select(User).where(User.external_auth_id == external_auth_id)
        return self.session.scalar(statement)

    def get_or_create(
        self,
        *,
        email: str,
        name: str,
        external_auth_id: str | None = None,
    ) -> User:
        if external_auth_id is not None:
            user = self.get_by_external_auth_id(external_auth_id)
            if user is not None:
                if user.email != email:
                    user.email = email
                if user.name != name:
                    user.name = name
                return user

        user = self.get_by_email(email)
        if user is not None:
            if user.name != name:
                user.name = name
            if external_auth_id is not None and user.external_auth_id != external_auth_id:
                user.external_auth_id = external_auth_id
            return user

        user = User(email=email, name=name, external_auth_id=external_auth_id)
        self.session.add(user)
        self.session.flush()
        return user
