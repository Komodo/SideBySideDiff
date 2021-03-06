"""
ADO MSSQL database backend for Django.

Requires adodbapi 2.0.1: http://adodbapi.sourceforge.net/
"""

from django.db.backends import BaseDatabaseWrapper, BaseDatabaseFeatures, BaseDatabaseOperations, util
try:
    import adodbapi as Database
except ImportError, e:
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured("Error loading adodbapi module: %s" % e)
import datetime
try:
    import mx
except ImportError:
    mx = None

DatabaseError = Database.DatabaseError
IntegrityError = Database.IntegrityError

# We need to use a special Cursor class because adodbapi expects question-mark
# param style, but Django expects "%s". This cursor converts question marks to
# format-string style.
class Cursor(Database.Cursor):
    def executeHelper(self, operation, isStoredProcedureCall, parameters=None):
        if parameters is not None and "%s" in operation:
            operation = operation.replace("%s", "?")
        Database.Cursor.executeHelper(self, operation, isStoredProcedureCall, parameters)

class Connection(Database.Connection):
    def cursor(self):
        return Cursor(self)
Database.Connection = Connection

origCVtoP = Database.convertVariantToPython
def variantToPython(variant, adType):
    if type(variant) == bool and adType == 11:
        return variant  # bool not 1/0
    res = origCVtoP(variant, adType)
    if mx is not None and type(res) == mx.DateTime.mxDateTime.DateTimeType:
        # Convert ms.DateTime objects to Python datetime.datetime objects.
        tv = list(res.tuple()[:7])
        tv[-2] = int(tv[-2])
        return datetime.datetime(*tuple(tv))
    if type(res) == float and str(res)[-2:] == ".0":
        return int(res) # If float but int, then int.
    return res
Database.convertVariantToPython = variantToPython

class DatabaseFeatures(BaseDatabaseFeatures):
    supports_tablespaces = True

class DatabaseOperations(BaseDatabaseOperations):
    def date_extract_sql(self, lookup_type, field_name):
        return "DATEPART(%s, %s)" % (lookup_type, field_name)

    def date_trunc_sql(self, lookup_type, field_name):
        if lookup_type == 'year':
            return "Convert(datetime, Convert(varchar, DATEPART(year, %s)) + '/01/01')" % field_name
        if lookup_type == 'month':
            return "Convert(datetime, Convert(varchar, DATEPART(year, %s)) + '/' + Convert(varchar, DATEPART(month, %s)) + '/01')" % (field_name, field_name)
        if lookup_type == 'day':
            return "Convert(datetime, Convert(varchar(12), %s))" % field_name

    def deferrable_sql(self):
        return " DEFERRABLE INITIALLY DEFERRED"

    def last_insert_id(self, cursor, table_name, pk_name):
        cursor.execute("SELECT %s FROM %s WHERE %s = @@IDENTITY" % (pk_name, table_name, pk_name))
        return cursor.fetchone()[0]

    def quote_name(self, name):
        if name.startswith('[') and name.endswith(']'):
            return name # Quoting once is enough.
        return '[%s]' % name

    def random_function_sql(self):
        return 'RAND()'

    def tablespace_sql(self, tablespace, inline=False):
        return "ON %s" % self.quote_name(tablespace)

class DatabaseWrapper(BaseDatabaseWrapper):
    features = DatabaseFeatures()
    ops = DatabaseOperations()
    operators = {
        'exact': '= %s',
        'iexact': 'LIKE %s',
        'contains': 'LIKE %s',
        'icontains': 'LIKE %s',
        'gt': '> %s',
        'gte': '>= %s',
        'lt': '< %s',
        'lte': '<= %s',
        'startswith': 'LIKE %s',
        'endswith': 'LIKE %s',
        'istartswith': 'LIKE %s',
        'iendswith': 'LIKE %s',
    }

    def _cursor(self, settings):
        if self.connection is None:
            if settings.DATABASE_NAME == '' or settings.DATABASE_USER == '':
                from django.core.exceptions import ImproperlyConfigured
                raise ImproperlyConfigured("You need to specify both DATABASE_NAME and DATABASE_USER in your Django settings file.")
            if not settings.DATABASE_HOST:
                settings.DATABASE_HOST = "127.0.0.1"
            # TODO: Handle DATABASE_PORT.
            conn_string = "PROVIDER=SQLOLEDB;DATA SOURCE=%s;UID=%s;PWD=%s;DATABASE=%s" % (settings.DATABASE_HOST, settings.DATABASE_USER, settings.DATABASE_PASSWORD, settings.DATABASE_NAME)
            self.connection = Database.connect(conn_string)
        return self.connection.cursor()
