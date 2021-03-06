GEVENT = False

import zlib
import datetime
import settings

import pymongo
import traceback
import os
import re
import multiprocessing
from Queue import Empty
from regs_models import *

from oxtail.matching import match

# arguments
from optparse import OptionParser
arg_parser = OptionParser()
arg_parser.add_option("-a", "--agency", dest="agency", action="store", type="string", default=None, help="Specify an agency to which to limit the dump.")
arg_parser.add_option("-d", "--docket", dest="docket", action="store", type="string", default=None, help="Specify a docket to which to limit the dump.")
arg_parser.add_option("-A", "--all", dest="process_all", action="store_true", default=False, help="Force a re-extraction of all documents in the system.")
arg_parser.add_option("-m", "--multi", dest="multi", action="store", type="int", default=multiprocessing.cpu_count(), help="Set number of worker processes.  Defaults to number of cores if not specified.")

# regex to find titles that are likely to have submitter names
NAME_FINDER = re.compile(r"^(public )?(comment|submission)s? (by|from) (?P<name>.*)$", re.I)

def get_text(view):
    if not view.content:
        return ''
    
    return view.content.read()

def process_doc(doc):
    # entity extraction
    for view in doc.views:
        if view.extracted == 'yes':
            view_matches = match(get_text(view), multiple=True)
            view.entities = list(view_matches.keys()) if view_matches else []

    for attachment in doc.attachments:
        for view in attachment.views:
            if view.extracted == 'yes':
                view_matches = match(get_text(view), multiple=True)
                view.entities = list(view_matches.keys()) if view_matches else []
    
    # submitter matches
    #   check if there's submitter stuff in the title
    title_match = NAME_FINDER.match(doc.title)

    #   next check details, which is where most title stuff lives
    details = doc.details
    #   stick "XXXX" between tokens because it doesn't occur in entity names
    submitter_matches = match(' XXXX '.join([
        # organization
        details.get('Organization_Name', ''),
        
        # submitter name
        ' '.join(
            filter(bool, [details.get('First_Name', ''), details.get('Last_Name', '')])
        ),

        # submitter representative
        details.get('Submitter_s_Representative', ''),

        # title_match if we found one
        title_match.groupdict()['name'] if title_match else '',
    ]))
    doc.submitter_entities = list(submitter_matches.keys()) if submitter_matches else []

    doc.entities_last_extracted = datetime.datetime.now()
        
    doc.save()

    return True

def process_worker(todo_queue):
    pid = os.getpid()
    print '[%s] Worker started.' % pid
    while True:
        try:
            doc = Doc._from_son(todo_queue.get())
        except Empty:
            print '[%s] Processing complete.' % pid
            return
        
        try:
            doc_success = process_doc(doc)
            print '[%s] Processing of doc %s succeeded.' % (pid, doc.id)
        except:
            print '[%s] Processing of doc %s failed.' % (pid, doc.id)
            traceback.print_exc()
        
        todo_queue.task_done()

def run(options, args):
    from regs_common.entities import load_trie_from_mongo
    import time

    pid = os.getpid()

    # load trie from the mongo database
    import_start = time.time()
    print '[%s] Loading trie...' % pid
    load_trie_from_mongo()
    print '[%s] Loaded trie in %s seconds.' % (pid, time.time() - import_start)

    query = {'deleted': False, 'scraped': 'yes', '$nor': [{'views.extracted': 'no'},{'attachments.views.extracted':'no'}]}
    if options.agency:
        query['agency'] = options.agency
    if options.docket:
        query['docket_id'] = options.docket
    if not options.process_all:
        query['entities_last_extracted'] = {'$exists': False}
    
    cursor = Doc.objects(__raw__=query)
    
    run_start = time.time()
    print '[%s] Starting analysis...' % pid

    num_workers = options.multi
    
    todo_queue = multiprocessing.JoinableQueue(num_workers * 3)
    
    processes = []
    for i in range(num_workers):
        proc = multiprocessing.Process(target=process_worker, args=(todo_queue,))
        proc.start()
        processes.append(proc)
    
    for doc in cursor:
        todo_queue.put(doc.to_mongo())
    
    todo_queue.join()

    for proc in processes:
        print 'Terminating worker %s...' % proc.pid
        proc.terminate()
    
    print '[%s] Completed analysis in %s seconds.' % (pid, time.time() - run_start)

