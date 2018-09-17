import os
import datetime
import pytz
from pytz import timezone

from flask import Flask
from flask import g
from flask import redirect
from flask import request
from flask import session
from flask import url_for, abort, render_template, flash, send_from_directory
from functools import wraps
from peewee import *
import config

from pw import encode_pw

import psutil
import pi_psutil

# config - aside from our database, the rest is for use by Flask
DATABASE = 'pilapse-sqlite.db'
DEBUG = True
SECRET_KEY = 'hin6bab8ge25*r=x&amp;+5$0kn=-#log$pt^#@vrqjld!^2ci@g*b'

# create a flask application - this ``app`` object will be used to handle
# inbound requests, routing them to the proper 'view' functions, etc
app = Flask(__name__)
app.config.from_object(__name__)

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
        
class Roles(BaseModel):
    name = TextField()

    def seed():
        name, created = Roles.get_or_create(name="admin")
        name, created = Roles.get_or_create(name="user")

        
# the user model specifies its fields (or columns) declaratively, like django
class User(BaseModel):
    username = CharField(unique=True)
    password = CharField()
    email = CharField()
    join_date = DateTimeField()
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
                'join_date' : datetime.datetime.now(),
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
    pub_date = DateTimeField()

class Settings(BaseModel):
    key = TextField()
    value = TextField()

    def get_value(key, type=str):
        value = Settings.get(Settings.key==key).value
        if type == bool:
            return value == "True"
        if type == int:
            return int(value)
        if type == float:
            return float(value)
        return str(value)

    def upsert(key, value):
        try:
            with database.atomic():
                #Upsert
                setting, created = Settings.get_or_create(
                    key=key,
                    defaults={'value': value}
                )
                setting.value=value
                setting.save()
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
            Settings.upsert(key, value)


# simple utility function to create and seed tables
def create_tables():
    # Tables need to be listed such that tables referening other tables are at the end
    tables = [Roles, User, Relationship, Message, Settings]

    def seed_tables(tables):
        for table in tables:
            table.seed()
    # Create tables
    with database:
        database.create_tables(tables)
    # Seed
    seed_tables(tables)
    
    
# flask provides a "session" object, which allows us to store information across
# requests (stored by default in a secure cookie).  this function allows us to
# mark a user as being logged-in by setting some values in the session data:
def auth_user(user):
    session['logged_in'] = True
    session['user_id'] = user.id
    session['username'] = user.username
    # TODO this needs to be moved outside of the cookie
    session['is_admin'] = is_admin()
    flash('You are logged in as %s' % (user.username))

# get the user from the session
def get_current_user():
    if session.get('logged_in'):
        return User.get(User.id == session['user_id'])

# Is the user from the session an admin
def is_admin():
    user = get_current_user()
    return user.is_role("admin")


# Decorator to mark an endpint as requiring admin privledges
# TODO: Load from DB, not cookie
def admin_required(f):
    @wraps(f)
    def inner(*args, **kwargs):
        if not session.get('is_admin'):
            abort(404)
        ret_val = f(*args, **kwargs)
        return ret_val
    return inner

# view decorator which indicates that the requesting user must be authenticated
# before they can access the view.  it checks the session to see if they're
# logged in, and if not redirects them to the login view.
def login_required(f):
    @wraps(f)
    def inner(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        try:
            ret_val = f(*args, **kwargs)
        except User.DoesNotExist:
            return redirect(url_for('login'))
        return ret_val
    return inner

# given a template and a SelectQuery instance, render a paginated list of
# objects from the query inside the template
def object_list(template_name, qr, var_name='object_list', **kwargs):
    kwargs.update(
        page=int(request.args.get('page', 1)),
        pages=qr.count() / 20 + 1)
    kwargs[var_name] = qr.paginate(kwargs['page'])
    return render_template(template_name, **kwargs)

# retrieve a single object matching the specified query or 404 -- this uses the
# shortcut "get" method on model, which retrieves a single object or raises a
# DoesNotExist exception if no matching object exists
# http://charlesleifer.com/docs/peewee/peewee/models.html#Model.get)
def get_object_or_404(model, *expressions):
    try:
        return model.get(*expressions)
    except model.DoesNotExist:
        abort(404)

# custom template filter -- flask allows you to define these functions and then
# they are accessible in the template -- this one returns a boolean whether the
# given user is following another user.
@app.template_filter('is_following')
def is_following(from_user, to_user):
    return from_user.is_following(to_user)

# Request handlers -- these two hooks are provided by flask and we will use them
# to create and tear down a database connection on each request.
@app.before_request
def before_request():
    g.db = database
    g.db.connect()

@app.after_request
def after_request(response):
    g.db.close()
    return response

# views -- these are the actual mappings of url to view function
@app.route('/')
def homepage():
    # depending on whether the requesting user is logged in or not, show them
    # either the public timeline or their own private timeline
    if session.get('logged_in'):
        return latest_video()
    else:
        return login()

@app.route('/latest_video/')
@login_required
def latest_video():
    # the private timeline exemplifies the use of a subquery -- we are asking for
    # messages where the person who created the message is someone the current
    # user is following.  these messages are then ordered newest-first.
    user = get_current_user()
    messages = (Message
                .select()
                .where(Message.user << user.following())
                .order_by(Message.pub_date.desc()))
    stats=get_system_stats()
    return object_list('latest_video.html', messages, 'message_list', stats=stats)

@app.route('/public/')
def public_timeline():
    # simply display all messages, newest first
    messages = Message.select().order_by(Message.pub_date.desc())
    return object_list('public_messages.html', messages, 'message_list')

@app.route('/videos/<path:path>', methods=['GET'])
def videos(path):
    static_url_path=Settings.get_value('encoder_video_path')
    if not os.path.isfile(os.path.join(static_url_path, path)):
        path = os.path.join(path, 'index.html')
        
    return send_from_directory(static_url_path, path)
    

@app.route('/join/', methods=['GET', 'POST'])
def join():
    if request.method == 'POST' and request.form['username']:
        try:
            with database.atomic():
                # Attempt to create the user. If the username is taken, due to the
                # unique constraint, the database will raise an IntegrityError.
                user_role=Roles.get(Roles.name == "user")
                user = User.create(
                    username=request.form['username'],
                    password=encode_pw(request.form['password']),
                    email=request.form['email'],
                    join_date=datetime.datetime.now(),
                    role=user_role
                )
            # mark the user as being 'authenticated' by setting the session vars
            auth_user(user)
            return redirect(url_for('homepage'))

        except IntegrityError:
            flash('That username is already taken')

    return render_template('join.html')

@app.route('/login/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and request.form['username']:
        try:
            pw_hash = encode_pw(request.form['password'])
            user = User.get(
                (User.username == request.form['username']) &
                (User.password == pw_hash))
        except User.DoesNotExist:
            flash('The password entered is incorrect')
        else:
            auth_user(user)
            return redirect(url_for('homepage'))

    return render_template('login.html')

@app.route('/logout/')
def logout():
    session.pop('logged_in', None)
    flash('You were logged out')
    return redirect(url_for('homepage'))

@app.route('/about/')
def about():
    return render_template('about.html')

def get_system_stats():
    stats={}

    # Get last update of video
    video_path = Settings.get_value('encoder_video_path') + '/' + Settings.get_value('encoder_video_output_filename')
    try:
        update_time = os.path.getmtime(video_path)
        update_time =  pytz.utc.localize(datetime.datetime.utcfromtimestamp(update_time))
        update_time = update_time.astimezone(timezone('US/Pacific'))
        update_time_str = update_time.strftime("%Y-%m-%d, %H:%M:%S %Z")
    except FileNotFoundError:
        update_time_str = "None"
    stats['update_time'] = update_time_str
    
    # Get capture status
    capture = Settings.get_value('capture_enable', type=bool)
    if capture:
        capture='<font size="4" color="red">Recording</font>'
    else:
        capture='<font size="4" color="black">Stopped</font>'
    stats['capture']=capture

    # Temp Status
    tempc = pi_psutil.get_cpu_temperature()
    stats['tempc'] = "%2.1f C" % tempc

    # RAM
    ram = psutil.virtual_memory()
    stats['ram_total'] = "%dMB" % (ram.total / 2**20)       # MiB.
    stats['ram_used'] = "%dMB" % (ram.used / 2**20)
    stats['ram_free'] = "%dMB" % (ram.free / 2**20)
    stats['ram_percent_used'] = "%2.1f%%" % (ram.percent)

    # DISK
    disk = psutil.disk_usage('/')
    stats['disk_total'] = "%2.1fGB" % (disk.total / 2**30)     # GiB.
    stats['disk_used'] = "%2.1fGB" % (disk.used / 2**30)
    stats['disk_free'] = "%2.1fGB" % (disk.free / 2**30)
    stats['disk_percent_used'] = "%2.1f%%" % (disk.percent)
    
    return stats
        
@app.route('/admin/')
@login_required
@admin_required
def admin():
    # Get forms for all settings and make available to render
    settings = Settings.select().order_by(Settings.key)
    forms = [ {'key': s.key, 'title': config.get_title(s.key), 'help': config.get_help(s.key), 'form': config.get_form_html(s.key, s.value) } for s in settings]
    # render page
    return render_template('admin.html', stats=get_system_stats(), setting_forms=forms)

@app.route('/settings/', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    if request.method == 'POST':
        print(request.form)
        
        flash('Updated')
    else:
        print(request.form)

    return admin()


@app.route('/following/')
@login_required
def following():
    user = get_current_user()
    return object_list('user_following.html', user.following(), 'user_list')

@app.route('/followers/')
@login_required
def followers():
    user = get_current_user()
    return object_list('user_followers.html', user.followers(), 'user_list')

@app.route('/users/')
def user_list():
    users = User.select().order_by(User.username)
    return object_list('user_list.html', users, 'user_list')

@app.route('/users/<username>/')
def user_detail(username):
    # using the "get_object_or_404" shortcut here to get a user with a valid
    # username or short-circuit and display a 404 if no user exists in the db
    user = get_object_or_404(User, User.username == username)

    # get all the users messages ordered newest-first -- note how we're accessing
    # the messages -- user.message_set.  could also have written it as:
    # Message.select().where(Message.user == user)
    messages = user.messages.order_by(Message.pub_date.desc())
    return object_list('user_detail.html', messages, 'message_list', user=user)

@app.route('/users/<username>/follow/', methods=['POST'])
@login_required
def user_follow(username):
    user = get_object_or_404(User, User.username == username)
    try:
        with database.atomic():
            Relationship.create(
                from_user=get_current_user(),
                to_user=user)
    except IntegrityError:
        pass

    flash('You are following %s' % user.username)
    return redirect(url_for('user_detail', username=user.username))

@app.route('/users/<username>/unfollow/', methods=['POST'])
@login_required
def user_unfollow(username):
    user = get_object_or_404(User, User.username == username)
    (Relationship
     .delete()
     .where(
         (Relationship.from_user == get_current_user()) &
         (Relationship.to_user == user))
     .execute())
    flash('You are no longer following %s' % user.username)
    return redirect(url_for('user_detail', username=user.username))

@app.route('/post/', methods=['GET', 'POST'])
@login_required
def post():
    user = get_current_user()
    if request.method == 'POST' and request.form['content']:
        message = Message.create(
            user=user,
            content=request.form['content'],
            pub_date=datetime.datetime.now())
        flash('Your message has been created')
        return redirect(url_for('user_detail', username=user.username))

    return render_template('post.html')


@app.route('/startCapture', methods=['POST'])
@login_required
@admin_required
def startCapture():
    Settings.upsert('capture_enable', True)
    flash('Capture started.')
    return redirect(url_for('admin'))


@app.route('/stopCapture', methods=['POST'])
@login_required
@admin_required
def stopCapture():
    Settings.upsert('capture_enable', False)
    flash('Capture stopped.')
    return redirect(url_for('admin'))


@app.route('/shutdown', methods=['POST'])
@login_required
@admin_required
def shutdown():
    SHUTDOWN_DELAY=1
    # Shutdown after 1 minute (seconds not possible on pi)
    cmd = "sudo shutdown -t %d" % SHUTDOWN_DELAY
    ret_value = os.system(cmd)
    if not ret_value:
        flash('Success. System shutdown scheduled for %d minute(s) from now.' % SHUTDOWN_DELAY)
    else:
        flash('Error. Failed to schedule system shutdown. Does the process have access?')
    return redirect(url_for('admin'))
                                                                                        
@app.context_processor
def _inject_user():
    try:
        user = get_current_user()
        return {'current_user': user }
    except User.DoesNotExist:
        return {}

# allow running from the command line
if __name__ == '__main__':
    # Create and seed tables
    create_tables()

    app.run(host="0.0.0.0",
            debug=False, # Debug mode consumes noticibly more CPU
            port=5000
    )
