from .main import *

engine = create_engine('postgresql+psycopg2://' + POSTGRES_USER + ':' + POSTGRES_PW + '@' + POSTGRES_URL + '/' + POSTGRES_DB, pool_size=num_fetch_threads, convert_unicode=True)
# Create database if it does not exist.
if not database_exists(engine.url):
  create_database(engine.url)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

class Config(Base):
  __tablename__ = 'config'
  _id = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True)
  created_at = Column(DateTime, default=datetime.datetime.now)
  updated_at = Column(DateTime, nullable=True)
  business_id = Column(String(256), nullable=False)
  kafka_topic = Column(String(256), nullable=False)
  network_id = Column(String(256), nullable=False)
  tenant_id = Column(String(256), nullable=False)
  resource_id = Column(String(256), nullable=False)
  reference_id = Column(String(256), nullable=False)
  timestamp_start = Column(DateTime, nullable=False)
  timestamp_end = Column(DateTime, nullable=True)
  status = Column(Integer, default=1)
  metrics = relationship("Metric")

  def __init__(self, business_id, kafka_topic, network_id, timestamp_start, timestamp_end, tenant_id, resource_id, reference_id):
    self.business_id = business_id
    self.kafka_topic = kafka_topic
    self.network_id = network_id
    self.timestamp_start = timestamp_start
    self.timestamp_end = timestamp_end
    self.tenant_id = tenant_id
    self.resource_id = resource_id
    self.reference_id = reference_id
        
  def toString(self):
    return ({'id': self._id,
             'created_at': self.created_at,
             'updated_at': self.updated_at,
             'businessID': self.business_id,
             'topic': self.kafka_topic,
             'networkID': self.network_id,
             'timestampStart': self.timestamp_start,
             'timestampEnd': self.timestamp_end,
             'metrics': [],
             'status': self.status,
             'tenant_id' : self.tenant_id,
             'resource_id' : self.resource_id,
             'reference_id' : self.reference_id})

class Metric(Base):
  __tablename__ = 'metric'
  _id = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True)
  config_id = Column(postgresql.UUID(as_uuid=True), ForeignKey('config._id'))
  metric_name = Column(String(256), nullable=False)
  metric_type = Column(String(256), nullable=False)
  aggregation_method = Column(String(256), nullable=True)
  step = Column(String(256), nullable=False)
  step_aggregation = Column(String(256), nullable=True)
  next_run_at = Column(DateTime, nullable=False)
  next_aggregation = Column(DateTime, nullable=True)
  status = Column(Integer, default=1)
  values = relationship("Value", cascade="all, delete")

  def __init__(self, metric_name, metric_type, aggregation_method, step, step_aggregation, config_id, next_run_at, next_aggregation):
    self.metric_name = metric_name
    self.metric_type = metric_type
    self.aggregation_method = aggregation_method
    self.step = step
    self.step_aggregation = step_aggregation
    self.config_id = config_id
    self.next_run_at = next_run_at
    self.next_aggregation = next_aggregation
        
  def toString(self):
    return ({'metricName': self.metric_name,
             'metricType': self.metric_type,
             'aggregationMethod': self.aggregation_method,
             'step': self.step,
             'step_aggregation': self.step_aggregation,
             'next_run_at': self.next_run_at,
             'next_aggregation': self.next_aggregation})

class Value(Base):
  __tablename__ = 'value'
  timestamp = Column(DateTime, nullable=False, primary_key=True)
  metric_id = Column(postgresql.UUID(as_uuid=True), ForeignKey('metric._id'), primary_key=True)
  metric_value = Column(Float, nullable=False)

  def __init__(self, timestamp, metric_id, metric_value):
    self.timestamp = timestamp
    self.metric_id = metric_id
    self.metric_value = metric_value

# ----------------------------------------------------------------#
seconds_per_unit = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

def convert_to_seconds(s):
  return int(s[:-1]) * seconds_per_unit[s[-1]]
 
def add_config(config: Config_Model):
  global db_session
  global wait_queue
  try:
    row = Config(config.businessID, config.topic, config.networkID, config.timestampStart, config.timestampEnd, config.tenantID, config.resourceID, config.referenceID)
    db_session.add(row)
    db_session.commit()
    response = row.toString()
    for metric in config.metrics:
      aggregation = None
      if metric.step_aggregation != None:
        sec_to_add = convert_to_seconds(metric.step_aggregation)
        aggregation = row.timestamp_start + relativedelta(seconds=sec_to_add)
      row_m = Metric(metric.metricName, metric.metricType, metric.aggregationMethod, metric.step, metric.step_aggregation, row._id, row.timestamp_start, aggregation)
      db_session.add(row_m)
      db_session.commit()
      #Read metric
      wait_queue.put((row_m.next_run_at, row.timestamp_start, row_m.step, row.timestamp_end, row_m._id, row_m.metric_name, row_m.metric_type, row_m.aggregation_method, row.business_id, row.kafka_topic, row.network_id, row.tenant_id, row.resource_id, row.reference_id, row_m.step_aggregation, row_m.next_aggregation, 0))
      #if row_m.aggregation_method != None:
      #  create_aggregate_view(row_m._id, row_m.aggregation_method, row_m.step_aggregation)
      response['metrics'].append(row_m.toString())
    return response
  except Exception as e:
    print(e)
    return -1

def get_config(config_id):
  try:
    config = Config.query.filter_by(_id=config_id).first()
    if config == None:
      return 0
    response = config.toString()
    metrics = Metric.query.filter_by(config_id=config_id).all()
    [response['metrics'].append(metric.toString()) for metric in metrics]
    return response
  except Exception as e:
    print(e)
    return -1

def get_configs():
  try:
    configs = Config.query.all()
    response = []
    for config in configs:
      add_metrics = config.toString()
      metrics = Metric.query.filter_by(config_id=config._id).all()
      [add_metrics['metrics'].append(metric.toString()) for metric in metrics]
      response.append(add_metrics)
    return response
  except Exception as e:
    print(e)
    return -1

def delete_metric_queue(metric_id):
  global wait_queue
  index = True
  while(index):
    index = False
    for i in range(len(wait_queue.queue)):
      if wait_queue.queue[i][4] == metric_id:
        del wait_queue.queue[i]
        index = True
        break
  return

def update_config(config_id, config):
  global db_session
  global wait_queue
  try:
    row = Config.query.filter_by(_id=config_id).first()
    if row == None:
      return 0
    if config.timestampEnd == None and config.metrics == None:
      return 1
      
    if config.timestampEnd != None and row.timestamp_end != None and config.timestampEnd <= row.timestamp_end:
      return 2
      
    row.updated_at = datetime.datetime.now()
    # Update config
    if config.timestampEnd != None:
      row.timestamp_end = config.timestampEnd
    db_session.commit()
    response = row.toString()
    # Update metrics
    # Delete old metrics
    metrics = Metric.query.filter_by(config_id=config_id).all()
    for metric in metrics:
      #drop_aggregate_view(metric._id, metric.aggregation_method)
      delete_metric_queue(metric._id)
      db_session.delete(metric)
    
    if config.metrics != None:
      #Create new metrics
      for metric in config.metrics:
        aggregation = None
        if metric.step_aggregation != None:
          sec_to_add = convert_to_seconds(metric.step_aggregation)
          aggregation = row.timestamp_start + relativedelta(seconds=sec_to_add)
        row_m = Metric(metric.metricName, metric.metricType, metric.aggregationMethod, metric.step, metric.step_aggregation, row._id, row.timestamp_start, aggregation)
        db_session.add(row_m)
        db_session.commit()
        response['metrics'].append(row_m.toString())
        wait_queue.put((row_m.next_run_at, row.timestamp_start, row_m.step, row.timestamp_end, row_m._id, row_m.metric_name, row_m.metric_type, row_m.aggregation_method, row.business_id, row.kafka_topic, row.network_id, row.tenant_id, row.resource_id, row.reference_id, row_m.step_aggregation, row_m.next_aggregation, 0))
      return response
    return get_config(config_id)
  except Exception as e:
    print(e)
    return -1

def update_next_run(metric_id):
  global db_session
  global wait_queue
  try:
    metric = Metric.query.filter_by(_id=metric_id).first()
    config = Config.query.filter_by(_id=metric.config_id).first()
    sec_to_add = convert_to_seconds(metric.step)
    old = metric.next_run_at
    next = old + relativedelta(seconds=sec_to_add)
    if config.timestamp_end != None and next > config.timestamp_end:
      metric.status = 0
      db_session.commit()
    else:
      metric.next_run_at = next
      db_session.commit()
      if metric.status == 1:
        wait_queue.put((metric.next_run_at, config.timestamp_start, metric.step, config.timestamp_end, metric._id, metric.metric_name, metric.metric_type, metric.aggregation_method, config.business_id, config.kafka_topic, config.network_id, config.tenant_id, config.resource_id, config.reference_id, metric.step_aggregation, metric.next_aggregation, 0))
        
    #Send aggregation
    if next >= metric.next_aggregation:
      update_aggregation(metric, config)
    return 1
  except Exception as e:
    #print(e)
    return -1

def update_aggregation(metric, config):
  global db_session
  global wait_queue
  try:
    # Send aggregation
    wait_queue.put((metric.next_aggregation, config.timestamp_start, metric.step, config.timestamp_end, metric._id, metric.metric_name, metric.metric_type, metric.aggregation_method, config.business_id, config.kafka_topic, config.network_id, config.tenant_id, config.resource_id, config.reference_id, metric.step_aggregation, metric.next_aggregation, 1))
    # Update next_aggregation
    sec_to_add = convert_to_seconds(metric.step_aggregation)
    next = metric.next_aggregation + relativedelta(seconds=sec_to_add)
    metric.next_aggregation = next
    db_session.commit()
    return 1
  except Exception as e:
    #print(e)
    return -1

def enable_config(config_id):
  global db_session
  global wait_queue
  try:
    config = Config.query.filter_by(_id=config_id).first()
    if config == None or (config.timestamp_end != None and config.timestamp_end < datetime.datetime.now()):
      return 0
    if config.status == 1:
      return 1
    config.status = 1
    config.updated_at = datetime.datetime.now()
    add_metrics = config.toString()
    metrics = Metric.query.filter_by(config_id=config._id).all()
    for metric in metrics:
      metric.status = 1
      db_session.commit()
      add_metrics['metrics'].append(metric.toString())
      wait_queue.put((metric.next_run_at, config.timestamp_start, metric.step, config.timestamp_end, metric._id, metric.metric_name, metric.metric_type, metric.aggregation_method, config.business_id, config.kafka_topic, config.network_id, config.tenant_id, config.resource_id, config.reference_id, metric.step_aggregation, metric.next_aggregation, 0))
    return add_metrics
  except Exception as e:
    print(e)
    return -1

def disable_config(config_id):
  global db_session
  global wait_queue
  try:
    config = Config.query.filter_by(_id=config_id).first()
    if config == None:
      return 0
    if config.status == 0:
      return 1
    config.status = 0
    config.updated_at = datetime.datetime.now()
    add_metrics = config.toString()
    metrics = Metric.query.filter_by(config_id=config._id).all()
    for metric in metrics:
      #drop_aggregate_view(metric._id, metric.aggregation_method)
      metric.status = 0
      add_metrics['metrics'].append(metric.toString())
      delete_metric_queue(metric._id)
    db_session.commit()
    return add_metrics
  except Exception as e:
    print(e)
    return -1

def delete_config(config_id):
  global db_session
  global wait_queue
  try:
    config = Config.query.filter_by(_id=config_id).first()
    if config == None:
      return 0
    metrics = Metric.query.filter_by(config_id=config._id).all()

    for metric in metrics:
      #drop_aggregate_view(metric._id, metric.aggregation_method)
      delete_metric_queue(metric._id)
      db_session.delete(metric)
      
    db_session.delete(config)
    db_session.commit()
    return 1
  except Exception as e:
    print(e)
    return -1

def load_database_metrics():
  global db_session
  global wait_queue
  try:
    result = db_session.execute("SELECT next_run_at, metric_name, metric_type, aggregation_method, step, business_id, kafka_topic, network_id, " \
                                       "tenant_id, resource_id, reference_id, timestamp_start, timestamp_end, metric._id, step_aggregation, " \
                                       "next_aggregation " \
                                "FROM metric join config on metric.config_id = config._id " \
                                "WHERE metric.status = 1;")
    for row in result:
      wait_queue.put((row['next_run_at'], row['timestamp_start'], row['step'], row['timestamp_end'], row['_id'], row['metric_name'], row['metric_type'], row['aggregation_method'], row['business_id'], row['kafka_topic'], row['network_id'], row['tenant_id'], row['resource_id'], row['reference_id'], row['step_aggregation'], row['next_aggregation'], 0))
    return 1
  except Exception as e:
    print(e)
    return -1

def insert_metric_value(metric_id, metric_value, timestamp):
  global db_session
  try:
    row = Value(timestamp, metric_id, metric_value)
    db_session.add(row)
    db_session.commit()
    return 1
  except Exception as e:
    print(e)
    return -1

def create_aggregate_view(metric_id, aggregation_method, step_aggregation):
  global db_session
  db_session.execute("CREATE VIEW \"agg_"+str(metric_id)+"_"+aggregation_method+"\" " \
                     "WITH (timescaledb.continuous) AS " \
                     "SELECT time_bucket(\'"+step_aggregation+"\', timestamp) AS bucket, "+aggregation_method+"(metric_value) AS aggregation " \
                     "FROM value " \
                     "WHERE metric_id = '"+str(metric_id)+"' " \
                     "GROUP BY bucket;")
  db_session.commit()
  return

def drop_aggregate_view(metric_id, aggregation_method):
  db_session.execute("DROP VIEW IF EXISTS \"agg_"+str(metric_id)+"_"+aggregation_method+"\" CASCADE;")
  db_session.commit()
  return

def get_last_aggregation(metric_id, aggregation_method, bucket, step_aggregation):
  global db_session
  #result = db_session.execute("REFRESH VIEW \"agg_"+str(metric_id)+"_"+aggregation_method+"\";" \
  #                            "SELECT * FROM \""+str(metric_id)+"_"+aggregation_method+"\" LIMIT 1;").fetchone()
  result = db_session.execute("SELECT "+aggregation_method+"(metric_value) " \
                              "FROM value " \
                              "WHERE metric_id = '"+str(metric_id)+"' and timestamp < '"+str(bucket)+"'::timestamp " \
                                    "and timestamp >= ('"+str(bucket)+"'::timestamp - interval '"+str(step_aggregation)+"');").fetchone()
  return result[0]

def create_index():
  global db_session
  #db_session.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;" \
  #                   "CREATE INDEX value_index ON value (timestamp ASC, metric_id);" \
  #                   "SELECT create_hypertable('value', 'timestamp', if_not_exists => TRUE);")
  db_session.execute("CREATE INDEX value_index ON value (timestamp ASC, metric_id);")
  db_session.commit()
  return

def drop_all_views():
  global db_session
  result = db_session.execute("SELECT 'DROP VIEW \"' || table_name || '\" CASCADE;' " \
                              "FROM information_schema.views " \
                              "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') AND " \
                                    "table_name !~ '^pg_' AND table_name LIKE 'agg_%';")
  for row in result:
    try:
      db_session.execute(row[0])
    except Exception:
      pass
  db_session.commit()
  return

def close_connection():
  global db_session
  db_session.remove()
  return
  
def reload_connection():
  global db_session
  db_session.remove()
  db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
  return

# ----------------------------------------------------------------#
# Reset db if env flag is True
if RESET_DB.lower() == 'true':
  try:
    try:
      db_session.commit()
      #drop_all_views()
      Base.metadata.drop_all(bind=engine)
    except Exception as e:
      print(e)
    Base.metadata.create_all(bind=engine)
    db_session.commit()
    create_index()
  except Exception as e:
    print(e)
    sys.exit(0)

# Create db if not exists
try:
  resp1 = Config.query.first()
  resp2 = Metric.query.first()
  resp2 = Value.query.first()
except Exception as e:
  try:
    Base.metadata.create_all(bind=engine)
    db_session.commit()
    create_index()
  except Exception as e:
    print(e)
    sys.exit(0)