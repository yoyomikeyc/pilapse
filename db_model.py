"""Database object model"""
from hashlib import md5
import ast
import datetime
from peewee import *
from pw import encode_pw
import config
import pytz
import os

# config - aside from our database, the rest is for use by Flask
DATABASE = 'pilapse-sqlite.db'

# create a peewee database instance -- our models will use this database to
# persist information
database = SqliteDatabase(DATABASE)

# model definitions -- the standard "pattern" is to define a base model class
# that specifies which database to use.  then, any subclasses will automatically
# use the correct storage. for more information, see:
# http://charlesleifer.com/docs/peewee/peewee/models.html#model-api-smells-like-django
class BaseModel(Model):
    """Base object model for all other db objects"""
    class Meta:
        database = database

    # seed function implementations must be idempotent.
    @staticmethod
    def seed():
        pass

    def local_time_str(self, t):
        t = pytz.utc.localize(t)
        system_tz = Settings.get_value_by_key('general_timezone')
        t = t.astimezone(pytz.timezone(system_tz))
        return t.strftime("%Y-%m-%d, %H:%M:%S %Z")

class KeyValuePairTypes(BaseModel):
    """Key Value Pair"""
    name = TextField(null=False)

    @staticmethod
    def seed():
        KeyValuePairTypes.get_or_create(name="bool")
        KeyValuePairTypes.get_or_create(name="dict")
        KeyValuePairTypes.get_or_create(name="int")
        KeyValuePairTypes.get_or_create(name="float")
        KeyValuePairTypes.get_or_create(name="str")

    # Each supported kvp type needs a function to convert the string representation of the
    # value to the appropriate type.  These functions need to have the format: _as_<type>()
    @staticmethod
    def _as_bool(value):
        """Internal method to convert value to boolean"""
        return value == "True"

    @staticmethod
    def _as_int(value):
        """Internal method to convert value to int"""
        return int(value)
    
    @staticmethod
    def _as_float(value):
        """Internal method to convert value to float"""
        return float(value)

    @staticmethod
    def _as_str(value):
        """Internal method to convert value to str"""
        return str(value)

    @staticmethod
    def _as_dict(value):
        """Internal method to convert value to dict"""
        return ast.literal_eval(value)

class KeyValuePair(BaseModel):
    """Generic class implementing Key-Value pair tables"""
    #This is not actually a table, but a class defining a set of functionalities for a table type.

    key = TextField(null=False)
    value = TextField(null=False)
    kvp_type = ForeignKeyField(KeyValuePairTypes)

    @classmethod
    def upsert_kvp(cls, key, value, as_type=str):
        """generic upsert function"""
        try:
            with database.atomic():
                kvp_type = KeyValuePairTypes.get(KeyValuePairTypes.name==as_type.__name__)
                #Upsert
                obj, created = cls.get_or_create(
                    key=key,
                    defaults={'value': value, 'kvp_type_id': kvp_type}
                )
                if not created:
                    obj.value = value
                    obj.kvp_type_id = kvp_type
                    obj.save()
        except IntegrityError:
            pass

    @classmethod
    def update_kvp(cls, key, value):
        """generic update function"""
        try:
            with database.atomic():
                try:
                    obj = cls.get(cls.key==key)
                except cls.DoesNotExist:
                    print("%s not found!" % key)
                    return
                obj.value = value
                obj.save()
        except IntegrityError:
            pass

        
    @classmethod
    def insert_kvp(cls, key, value, as_type=str):
        """insert (key, value) pair into settings table if key not present.
        Returns true if actually created."""
        kvp_type = KeyValuePairTypes.get(KeyValuePairTypes.name==as_type.__name__)
        obj, created = cls.get_or_create(
            key=key,
            defaults={'value': value, 'kvp_type_id': kvp_type}
        )
        return created
        
    @classmethod
    def get_value_by_key(cls, key):
        # Get value
        try:         
            kvp = cls.select(cls, KeyValuePairTypes.name.alias('type_name')) \
                     .join(KeyValuePairTypes, on=KeyValuePairTypes.id==cls.kvp_type_id) \
                     .where(cls.key == key).objects().get()
        except cls.DoesNotExist:
            return None
        # Cast to appropriate type
        type_cast_fn_name = "_as_%s" % kvp.type_name        
        type_cast_fn = getattr(KeyValuePairTypes, type_cast_fn_name)
        return type_cast_fn(kvp.value)
              
class Roles(BaseModel):
    name = TextField()

    @staticmethod
    def seed():
        Roles.get_or_create(name="admin")
        Roles.get_or_create(name="user")

class Sessions(BaseModel):
    description = TextField(null=True)
    started_at = DateTimeField(null=False, default=datetime.datetime.utcnow)
    ended_at = DateTimeField(null=True)
    image_start = IntegerField(unique=True, null=False, constraints=[Check('image_start >= 0')])
    image_end = IntegerField(unique=True, null=True, constraints=[Check('image_end >= -1')])

    def num_frames(self):
        """Returns the number of frames in this session.  If the session is not complete,
        the number of frames so far is used."""
        image_end = self.image_end
        if image_end is None:
            image_end = States.get_image_num()
        # image_start / image_end are inclusive.
        return (image_end - self.image_start) + 1

    def offset(self, string=False):
        """Returns a float representing the offset of session (in seconds) from start
        of video given current framerate"""
        frame_rate = Settings.get_value_by_key('encoder_video_frame_rate')
        seconds = self.image_start * (1.0 / frame_rate)
        if string:
            hours = int(seconds / 3600)
            seconds -= (hours * 3600)
            minutes = int(seconds / 60)
            seconds -= (minutes * 60)
            seconds = int(seconds)
            return "%02d:%02d:%02d" % (hours, minutes, seconds)
        return seconds

    def duration(self, string=False):
        """Return the duration of the session as a number of hours. If the session is not complete
        (ended_at is NULL), now() is used instead. Returns a float, unless string==True"""
        ended_at = self.ended_at
        if ended_at is None:
            ended_at = datetime.datetime.utcnow()
        delta = ended_at - self.started_at
        hours = delta.seconds / (60.0 * 60.0)
        if string:
            return "%2.1f" % hours
        return hours

    @staticmethod
    def end_session(description):
        """Mark the currentl active session as ended by setting the ended_at time and description"""
        try:
            with database.atomic():
                try:
                    session = Sessions.get(Sessions.ended_at.is_null())
                    image_num = States.get_image_num()
                    # If the image number hasnt been incremented,
                    # then this session contains no images.
                    if session.image_start == image_num:
                        session.delete_instance()
                        return
                    session.ended_at = datetime.datetime.utcnow()
                    session.description = description
                    # image_start / image_end are inclusive.
                    session.image_end = image_num - 1
                    session.save()
                except Sessions.DoesNotExist:
                    pass
        except IntegrityError:
            pass
    @staticmethod
    def start_session():
        try:
            with database.atomic():
                image_num = States.get_image_num()
                defaults = {
                    'image_end' : None,
                    'started_at' : datetime.datetime.utcnow(),
                    'ended_at' : None,
                    'description' : None,
                }
                Sessions.get_or_create(image_start=image_num, defaults=defaults)
        except IntegrityError:
            pass
# the user model specifies its fields (or columns) declaratively, like django
class Users(BaseModel):
    username = CharField(unique=True, null=False)
    password = CharField(null=False)
    email = CharField(null=False, unique=True)
    join_date = DateTimeField(default=datetime.datetime.utcnow)
    role = ForeignKeyField(Roles)

    @staticmethod
    def seed():
        """seed Users table with admin user"""
        # Load config from yaml
        yaml_config = config.load_config()

        admin_role = Roles.get(Roles.name == "admin")
        # Create admin user
        defaults = {
            'password': encode_pw(yaml_config['admin_password']),
            'email' : yaml_config['admin_email'],
            'join_date' : datetime.datetime.now(pytz.UTC),
            'role' : admin_role
        }
        Users.get_or_create(
            username=yaml_config['admin_username'],
            defaults=defaults
        )

    # it often makes sense to put convenience methods on model instances, for
    # example, "give me all the users this user is following":
    def following(self):
        # query other users through the "relationship" table
        return (Users
                .select()
                .join(Relationships, on=Relationships.to_user)
                .where(Relationships.from_user == self)
                .order_by(Users.username))

    def is_role(self, role):
        """Checks if user has the specified role string"""
        return (Users
                .select()
                .join(Roles, on=(Users.role_id == Roles.id))
                .where(Roles.name == role).exists())

    def followers(self):
        """Returns list of followers of user"""
        return (Users
                .select()
                .join(Relationships, on=Relationships.from_user)
                .where(Relationships.to_user == self)
                .order_by(Users.username))

    def is_following(self, user):
        return (Relationships
                .select()
                .where(
                    (Relationships.from_user == self) &
                    (Relationships.to_user == user))
                .exists())

    def gravatar_url(self, size=80):
        """Returns gravatar URL for user."""
        return 'http://www.gravatar.com/avatar/%s?d=identicon&s=%d' % \
            (md5(self.email.strip().lower().encode('utf-8')).hexdigest(), size)


# this model contains two foreign keys to user -- it essentially allows us to
# model a "many-to-many" relationship between users.  by querying and joining
# on different columns we can expose who a user is "related to" and who is
# "related to" a given user
class Relationships(BaseModel):
    from_user = ForeignKeyField(Users, backref='relationships')
    to_user = ForeignKeyField(Users, backref='related_to')

    class Meta:
        indexes = (
            # Specify a unique multi-column index on from/to-user.
            (('from_user', 'to_user'), True),
        )


# a dead simple one-to-many relationship: one user has 0..n messages, exposed by
# the foreign key.  because we didn't specify, a users messages will be accessible
# as a special attribute, Users.message_set
class Messages(BaseModel):
    user = ForeignKeyField(Users, backref='messages')
    content = TextField()
    pub_date = DateTimeField(default=datetime.datetime.utcnow)

class States(KeyValuePair):
    """States object for storing persistent system state"""

    @staticmethod
    def set_image_num(num):
        States.upsert_kvp("image_num", num, as_type=int)

    @staticmethod
    def get_image_num():
        return States.get_value_by_key("image_num")

    @staticmethod
    def seed():
        # Todo just make a set_image_num, but chnage from upsert to insert
        if States.get_image_num() is None:
            States.set_image_num(0)
        States.upsert_kvp('reinit', True, as_type=bool)
        
class Settings(KeyValuePair):
    """Settings object for storing system settings"""

    @staticmethod
    def seed():
        # Load config from yaml
        yaml_config = config.load_config()

        for key, value in yaml_config.items():
            # skip admin related since that belongs in the user table
            # skip webserver_secret as this should never be in the yaml file
            if key in ["admin_username", "admin_password", "admin_email", "webserver_secret"]:
                continue
            # Create setting
            Settings.insert_kvp(key, value, as_type=type(value))
        # Seed with secret key for session signing
        secret = os.urandom(32).decode('unicode_escape')
        Settings.insert_kvp('webserver_secret', secret, as_type=str)



# simple utility function to create and seed tables
def create_tables():
    """Create all tables in database"""
    # Tables need to be listed such that tables referening other tables are at the end
    tables = [KeyValuePairTypes, Roles, Users, Relationships, Messages, Settings, Sessions, States]

    def seed_tables(tables):
        for table in tables:
            table.seed()
    # Create tables
    with database:
        database.create_tables(tables)
    # Seed
    seed_tables(tables)

