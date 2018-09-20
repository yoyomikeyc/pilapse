import ast
import datetime
from peewee import *
from pw import encode_pw
import config
from hashlib import md5
import pytz

# config - aside from our database, the rest is for use by Flask
DATABASE = 'pilapse-sqlite.db'
SECRET_KEY = 'hin6bab8ge25*r=x&amp;+5$0kn=-#log$pt^#@vrqjld!^2ci@g*b'

# create a peewee database instance -- our models will use this database to
# persist information
database = SqliteDatabase(DATABASE)

# model definitions -- the standard "pattern" is to define a base model class
# that specifies which database to use.  then, any subclasses will automatically
# use the correct storage. for more information, see:
# http://charlesleifer.com/docs/peewee/peewee/models.html#model-api-smells-like-django
class BaseModel(Model):
    class Meta:
        database = database
        
    # seed function implementations must be idempotent.    
    def seed():
        pass

    def local_time_str(self, t):
        t = pytz.utc.localize(t)
        system_tz = Settings.get_value('general_timezone')
        t = t.astimezone(pytz.timezone(system_tz))
        return t.strftime("%Y-%m-%d, %H:%M:%S %Z")
        
class Roles(BaseModel):
    name = TextField()

    def seed():
        name, created = Roles.get_or_create(name="admin")
        name, created = Roles.get_or_create(name="user")

class Sessions(BaseModel):
    description = TextField(null=True)
    started_at = DateTimeField(null=False, default=datetime.datetime.utcnow)
    ended_at   = DateTimeField(null=True)
    image_start = IntegerField(unique=True, null=False, constraints=[Check('image_start >= 0')])
    image_end   = IntegerField(unique=True, null=True,  constraints=[Check('image_end >= -1')])
    
    def num_frames(self):
        """Returns the number of frames in this session.  If the session is not complete, the number of frames so far is used."""
        image_end = self.image_end 
        if image_end is None:
            image_end = State.get_image_num()
        # image_start / image_end are inclusive.
        return (image_end - self.image_start) + 1

    def offset(self, string=False):
        """Returns a float representing the offset of session (in seconds) from start of video given current framerate"""
        frame_rate =  float(Settings.get_value('encoder_video_frame_rate'))
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
        """Return the duration of the session as a number of hours. If the session is not complete (ended_at is NULL), now() is used instead. Returns a float, unless string==True"""
        ended_at = self.ended_at 
        if ended_at is None:
            ended_at = datetime.datetime.utcnow()
        delta = ended_at - self.started_at
        hours = delta.seconds / (60.0 * 60.0)
        if string:
            return "%2.1f" % hours
        return hours
    
    def end_session(description):
        try:
            with database.atomic():
                try:
                    session = Sessions.get(Sessions.ended_at.is_null())
                    image_num = State.get_image_num()
                    # If the image number hasnt been incremented, then this session contains no images.
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
    def start_session():
        image_num = State.get_image_num()
        session, created = \
            Sessions.get_or_create(image_start=image_num, defaults={ \
                                                                     'image_end' : None,
                                                                     'started_at':datetime.datetime.utcnow(),
                                                                     'ended_at':None,
                                                                     'description':None, }
            )
        
# the user model specifies its fields (or columns) declaratively, like django
class User(BaseModel):
    username = CharField(unique=True, null=False)
    password = CharField(null=False)
    email = CharField(null=False, unique=True)
    join_date = DateTimeField(default=datetime.datetime.utcnow)
    role = ForeignKeyField(Roles)
    
    def seed():
        # Load config from yaml
        yaml_config = config.load_config()

        admin_role = Roles.get(Roles.name=="admin")
        # Create admin user
        user, created = User.get_or_create(
            username = yaml_config['admin_username'],
            defaults={
                'password': encode_pw(yaml_config['admin_password']),
                'email' : yaml_config['admin_email'],
                'join_date' : datetime.datetime.now(pytz.UTC),
                'role' : admin_role
            }
        )

    # it often makes sense to put convenience methods on model instances, for
    # example, "give me all the users this user is following":
    def following(self):
        # query other users through the "relationship" table
        return (User
                .select()
                .join(Relationship, on=Relationship.to_user)
                .where(Relationship.from_user == self)
                .order_by(User.username))

    def is_role(self, role):
        return (User
                .select()
                .join(Roles, on=(User.role_id ==Roles.id))
                .where(Roles.name == role).exists())
    
    def followers(self):
        return (User
                .select()
                .join(Relationship, on=Relationship.from_user)
                .where(Relationship.to_user == self)
                .order_by(User.username))

    def is_following(self, user):
        return (Relationship
                .select()
                .where(
                    (Relationship.from_user == self) &
                    (Relationship.to_user == user))
                .exists())

    def gravatar_url(self, size=80):
        return 'http://www.gravatar.com/avatar/%s?d=identicon&s=%d' % \
            (md5(self.email.strip().lower().encode('utf-8')).hexdigest(), size)


# this model contains two foreign keys to user -- it essentially allows us to
# model a "many-to-many" relationship between users.  by querying and joining
# on different columns we can expose who a user is "related to" and who is
# "related to" a given user
class Relationship(BaseModel):
    from_user = ForeignKeyField(User, backref='relationships')
    to_user = ForeignKeyField(User, backref='related_to')

    class Meta:
        indexes = (
            # Specify a unique multi-column index on from/to-user.
            (('from_user', 'to_user'), True),
        )


# a dead simple one-to-many relationship: one user has 0..n messages, exposed by
# the foreign key.  because we didn't specify, a users messages will be accessible
# as a special attribute, User.message_set
class Message(BaseModel):
    user = ForeignKeyField(User, backref='messages')
    content = TextField()
    pub_date = DateTimeField(default=datetime.datetime.utcnow)

class State(BaseModel):
    key = TextField(null=False)
    value = TextField(null=False)

    def upsert(key, value):
        upsert_helper(State, key, value)

    def get_value(key):
        with database.atomic():
            try:
                val = State.get(State.key==key).value
            except State.DoesNotExist:
                val = None
        return val
    def get_int_value(key):
        val = State.get_value(key)
        if val is not None:
            val = int(val)
        return val
    
    def set_image_num(num):
        State.upsert("image_num", num)

    def set_seg_num(num):
        State.upsert("seg_num", num)

    def get_image_num():
        return State.get_int_value("image_num")

    def get_seg_num():
        return State.get_int_value("seg_num")

class Settings(BaseModel):
    key = TextField(null=False)
    value = TextField(null=False)

    def get_value(key, type=str):
        value = Settings.get(Settings.key==key).value
        if type == bool:
            return value == "True"
        if type == int:
            return int(value)
        if type == float:
            return float(value)
        if type == dict:
            return ast.literal_eval(value)
        return str(value)

    def upsert(key, value):
        upsert_helper(Settings, key, value)

    def insert_row(key, value):
        """insert (key,value) into settings table if not present.  Returns true if actually created."""
        try:
            with database.atomic():
                #Upsert
                setting, created = Settings.get_or_create(
                    key=key,
                    defaults={'value': value}
                )
                return created
        except IntegrityError:
            pass

    def seed():
        # Load config from yaml
        yaml_config = config.load_config()
        
        for key, value in yaml_config.items():
            # skip admin related
            if "admin" in key:
                continue
            # Create setting
            Settings.insert_row(key, value)


# simple utility function to create and seed tables
def create_tables():
    # Tables need to be listed such that tables referening other tables are at the end
    tables = [Roles, User, Relationship, Message, Settings, Sessions, State]

    def seed_tables(tables):
        for table in tables:
            table.seed()
    # Create tables
    with database:
        database.create_tables(tables)
    # Seed
    seed_tables(tables)

    
def upsert_helper(table, key, value):
    try:
        with database.atomic():
            #Upsert
            setting, created = table.get_or_create(
                key=key,
                defaults={'value': value}
            )
            setting.value = value
            setting.save()
    except IntegrityError:
        pass
