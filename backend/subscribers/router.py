class SubscriberRouter:
    """
    Route all ``subscribers`` models to the ``landing`` database.

    A return value of ``None`` means "no opinion" — Django falls back
    to the ``default`` database for everything else.
    """

    def db_for_read(self, model, **hints):
        if model._meta.app_label == "subscribers":
            return "landing"
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == "subscribers":
            return "landing"
        return None

    def allow_relation(self, obj1, obj2, **hints):
        # Allow relations only within the same database
        db1 = (
            "landing" if obj1._meta.app_label == "subscribers" else "default"
        )
        db2 = (
            "landing" if obj2._meta.app_label == "subscribers" else "default"
        )
        if db1 == db2:
            return None  # no opinion — let Django decide
        return False

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == "subscribers":
            return db == "landing"
        # For everything else, use the default database
        if db == "landing":
            return False
        return None  # no opinion — let Django decide
