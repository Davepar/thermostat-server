import jinja2
import json
import logging
import os
import random
import string
import urllib2
import webapp2
from datetime import datetime, timedelta
from dateutil import parser, tz
from google.appengine.api import users
from google.appengine.ext import ndb
from google.appengine.ext.webapp import template

JINJA_ENV = jinja2.Environment(
  loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
  extensions=['jinja2.ext.autoescape'],
  autoescape=True,
)

# Time zones
dt_schedule = ',M3.2.0,M11.1.0'
time_zones = [
  ('Eastern', 'ET', 'EST+5EDT' + dt_schedule),
  ('Central', 'CT', 'CST+6CDT' + dt_schedule),
  ('Mountain', 'MT', 'MST+7MDT' + dt_schedule),
  ('Arizona', 'AZT', 'MST+7'),
  ('Pacific', 'PT', 'PST+8PDT' + dt_schedule),
  ('Alaska', 'AKT', 'AKST+9AKDT' + dt_schedule),
  ('Hawaii-Aleutian', 'HAT', 'HAST+10HADT' + dt_schedule),
  ('Hawaii', 'HT', 'HAST+10'),
]
tzinfos = dict([(t[1], tz.tzstr(t[2])) for t in time_zones])
tz_select_array = [{'abbr': t[1], 'name': t[0]} for t in time_zones]
default_tz = tz_select_array[0]['abbr']

class IdData(ndb.Model):
  user_id = ndb.StringProperty('u')
  token = ndb.StringProperty('t')
  next_temp_change = ndb.DateTimeProperty('n')
  schedule_id = ndb.StringProperty('c')
  timezone = ndb.StringProperty('z')
  schedule = ndb.TextProperty('s')

  @classmethod
  def get_key(cls, t_id):
    return ndb.Key('Id', t_id)

  @classmethod
  def get_id(cls, t_id):
    key = cls.get_key(t_id)
    return cls.query(ancestor=key).get()

class ThermostatData(ndb.Model):
  temperature = ndb.IntegerProperty('t')
  humidity = ndb.IntegerProperty('h')
  num_averaged = ndb.IntegerProperty('n', default=1)
  set_temperature = ndb.IntegerProperty('s')
  hold = ndb.BooleanProperty('o')
  time = ndb.DateTimeProperty('i', indexed=True)
  heat_on = ndb.BooleanProperty('e')

  @classmethod
  def get_key(cls, t_id):
    return ndb.Key('Thermostat', t_id)

  @classmethod
  def query_readings(cls, t_id):
    key = cls.get_key(t_id)
    return cls.query(ancestor=key).order(-cls.time)

  @classmethod
  def query_oneday_readings(cls, t_id):
    key = cls.get_key(t_id)
    one_day_ago = datetime.utcnow() - timedelta(hours=24)
    return cls.query(cls.time > one_day_ago, ancestor=key).order(-cls.time)


class PostData(webapp2.RequestHandler):
  def get(self):
    time_now = datetime.utcnow()
    # Get some of the values from the query string
    t_id = self.request.get('id')
    if not t_id:
      self.response.write('Error: invalid ID')
      return

    id_data = IdData.get_id(t_id)
    if id_data is None:
      self.response.write('Error: unknown ID')
      return

    token = self.request.get('k')
    if token != id_data.token:
      self.response.write('Error: invalid token')
      return

    # Get previously saved record
    prev_reading = last_reading = None
    readings = ThermostatData.query_readings(t_id).fetch(2)
    if len(readings) == 0:
      # Create a fake last_reading with some default values
      last_reading = ThermostatData(
          temperature=680, humidity=500,
          set_temperature=680, hold=False, heat_on=False
      )
    else:
      last_reading = readings[0]
      if len(readings) > 1:
        prev_reading = readings[1]

    # Get current temperature from request
    temp = self.request.get('t', None)
    if temp is None:
      temp = last_reading.temperature
    else:
      temp = int(temp)

    # Get current humidity from request
    hum = self.request.get('h', None)
    if hum is None:
      hum = last_reading.humidity
    else:
      hum = int(hum)

    # Get "hold temperature" from request
    hold = self.request.get('d', None)
    if hold is None:
      hold = last_reading.hold
    else:
      hold = (hold == 'y')

    # Get set temperature from request
    set_temp = self.request.get('s', None)
    if set_temp is None:
      set_temp = last_reading.set_temperature
      # If holding temp, ignore schedule
      if (not hold and id_data.schedule_id
            and datetime.utcnow() > id_data.next_temp_change):
          set_temp, next_temp_change = get_next_event(id_data.schedule)
          id_data.next_temp_change = next_temp_change
          id_data.put()
    else:
      set_temp = int(set_temp)

    # Determine whether to turn heat on or off
    if last_reading.heat_on:
      heat_on = (temp < (set_temp + 4))
    else:
      heat_on = (temp < (set_temp - 4))

    logging.info('%s,%s,%s,%s,%s' % (temp,hum,set_temp,hold,heat_on))

    storage_interval = timedelta(minutes=5, seconds=10)
    if not prev_reading or prev_reading.time + storage_interval < time_now:
      new_data = ThermostatData(
          parent=ThermostatData.get_key(t_id),
          time=time_now,
          temperature=temp,
          humidity=hum,
          set_temperature=set_temp,
          hold=hold,
          heat_on=heat_on,
      )
      new_data.put()
    else:
      # Average together last 5 minutes worth of readings to reduce data storage
      num_averaged = last_reading.num_averaged
      last_reading.populate(
        time=time_now,
        temperature=add_value_to_average(last_reading.temperature, temp, num_averaged),
        humidity=add_value_to_average(last_reading.humidity, hum, num_averaged),
        num_averaged=num_averaged + 1,
        set_temperature=set_temp,
        hold=hold,
        heat_on=heat_on,
      )
      last_reading.put()


    self.response.write('%s,%s,%s' % (set_temp, int(hold), int(heat_on)))


class GetHeat(webapp2.RequestHandler):
  def get(self):
    t_id = self.request.get('id')
    reading = ThermostatData.query_readings(t_id).get()
    self.response.write('%s' % int(reading.heat_on))


class Schedule(webapp2.RequestHandler):
  def post(self):
    message = None
    t_id = self.request.get('id')
    s_id = self.request.get('scheduleId')
    # Convert from array index back to time zone abbreviation
    timezone = tz_select_array[int(self.request.get('tz'))]['abbr']
    cur_user = users.get_current_user()
    id_data = IdData.get_id(t_id)
    if cur_user and id_data.user_id == cur_user.user_id():
      schedule = get_schedule(s_id, timezone)
      if schedule:
        set_temperature, next_temp_change = get_next_event(schedule)
        id_data.schedule_id = s_id
        id_data.timezone = timezone
        id_data.schedule = schedule
        id_data.next_temp_change = next_temp_change
        id_data.put()
        # print 'Next change: %s' % next_temp_change

        last_reading = ThermostatData.query_readings(t_id).get()
        if last_reading and not last_reading.hold:
          last_reading.set_temperature = set_temperature
          last_reading.put()
          message = 'Successfully updated schedule'
        else:
          # TODO: Create new ThermostatData
          pass
      else:
        message = 'Could not process schedule'
    else:
      message = 'Must be logged in to update schedule'

    url = '/?id=' + t_id
    if message:
      url += '&msg=' + message
    return self.redirect(url)


class Thermostat(webapp2.RequestHandler):
  def get(self):
    info = {
      'id': None,
      'login': None,
      'claimed': False,
      'owned': False,
      'message': self.request.get('msg'),
      'timezones': tz_select_array,
    }
    # Check if ID specified
    # TODO: ID can only be up to 11 characters long
    t_id = self.request.get('id')
    if t_id:
      info['id'] = t_id
      # Check if user is signed in
      cur_user = users.get_current_user()
      if cur_user is None:
        info['login'] = str(users.create_login_url('/?id=' + t_id))
      # See if the ID is claimed
      id_data = IdData.get_id(t_id)
      if id_data is None:
        claim_id = self.request.get('claim') == 'y'
        if claim_id:
          if cur_user is None:
            return self.redirect(info['login'])
          id_data = IdData(
            parent=IdData.get_key(t_id),
            user_id = cur_user.user_id(),
            token = create_token(),
          )
          id_data.put()
          return self.redirect('/?id=' + t_id)
      else:
        info['claimed'] = True
        # See if user owns the ID
        if cur_user and id_data.user_id == cur_user.user_id():
          info['token'] = id_data.token
          info['scheduleId'] = id_data.schedule_id
          info['tz'] = id_data.timezone or default_tz

        # Reformat readings to put them into the template
        readings = ThermostatData.query_oneday_readings(t_id)
        last_reading = None
        values = []
        for reading in readings:
          # The last reading is the first in the list
          if last_reading is None:
            last_reading = reading
          time_str = str(reading.time)
          values.append((time_str.split('.')[0], reading.temperature, reading.humidity, reading.set_temperature))
        if last_reading:
          info['heat'] = last_reading.heat_on
          info['hold'] = last_reading.hold
          info['set_temp'] = last_reading.set_temperature
          info['data'] = values

    template = JINJA_ENV.get_template('index.html')
    self.response.write(template.render({'info': json.dumps(info, separators=(',',':'))}))


def normalize(dt_str, local_today):
  dt = parser.parse(dt_str, tzinfos=tzinfos, default=local_today).astimezone(tz.tzutc()).replace(tzinfo=None)

  # Normalize each datetime to within one week from now
  now = datetime.utcnow()
  oneweek = timedelta(days=7)
  oneweek_from_now = now + oneweek
  while dt < now:
    dt += oneweek
  while dt > oneweek_from_now:
    dt -= oneweek
  return dt

def add_value_to_average(old_value, new_value, num_averaged):
  return (old_value * num_averaged + new_value) / (num_averaged + 1)

def create_token():
  random.seed()
  return ''.join([random.choice(string.ascii_letters + string.digits) for x in range(8)])

def get_schedule(schedule_id, timezone):
  url = 'https://spreadsheets.google.com/feeds/list/%s/od6/public/values?alt=json' % schedule_id
  try:
    response = urllib2.urlopen(url)
    content = response.read()
  except urllib2.URLError:
    logging.warning('Warning: could not retrieve spreadsheet data for %s' % schedule_id)
    return False

  try:
    data = json.loads(content)
  except ValueError:
    logging.error('Error: invalid JSON format for spreadsheet %s' % schedule_id)
    return False

  if 'feed' not in data or 'entry' not in data['feed']:
    logging.warning('Warning: invalid data format for %s' % schedule_id)
    return False

  data_keys = [
    ('gsx$day', 'day'),
    ('gsx$time', 'time'),
    ('gsx$temperature', 'temperature'),
  ]

  # Process entries in spreadsheet
  schedule = []
  for entry in data['feed']['entry']:
    result = {}
    for entry_key, result_key in data_keys:
      if entry_key not in entry or '$t' not in entry[entry_key]:
        logging.warning('Warning: key not found for %s: %s' % (schedule_id, entry_key))
        return False
      result[result_key] = entry[entry_key]['$t']

    day_time = '%s %s %s' % (result['day'], result['time'], timezone)
    try:
      # TODO: Ensure valid timezone
      result['datetime'] = parser.parse(day_time)
    except ValueError:
      logging.warning('Warning: invalid time format for %s: %s' % (schedule_id, day_time))
      return False
    try:
      result['temperature'] = int(result['temperature'])
    except ValueError:
      logging.warning('Warning: invalid temperature format for %s: %s'
          % (schedule_id, result['temperature']))
      return False

    schedule.append({'dt': day_time, 't': result['temperature']})

  return json.dumps(schedule, separators=(',', ':'))

def get_next_event(schedule):
  schedule = json.loads(schedule)
  # TODO: This needs some clean up
  time_zone = tzinfos[schedule[0]['dt'].split(' ')[-1]]
  midnight = {'hour': 0, 'minute': 0, 'second': 0, 'microsecond': 0, 'tzinfo': None}
  local_today = datetime.utcnow().replace(tzinfo=tz.tzutc()).astimezone(time_zone).replace(**midnight)
  current_schedule = [{
    'dt': normalize(entry['dt'], local_today),
    't': entry['t'],
  } for entry in schedule]
  current_schedule.sort(key=lambda x:x['dt'])
  return current_schedule[-1]['t'] * 10, current_schedule[0]['dt']


app = webapp2.WSGIApplication([
    ('/post', PostData),
    ('/getheat', GetHeat),
    ('/update', Schedule),
    ('/', Thermostat),
], debug=True)
