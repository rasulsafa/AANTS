# PSL

from collections import defaultdict
from email.message import EmailMessage

import aiosmtplib
import asyncio
import time
import sys

# THIRD PARTY

from bs4 import BeautifulSoup

import requests
import lxml

# PROJECT

import secret

# CONSTANTS

# NOTE: Must update each term
# TODO: Find a way to dynamically update without manual intervtion
_TERM = '2019-92'
_WEBSOC = 'https://www.reg.uci.edu/perl/WebSoc?'
_OPEN_SUBJECT = "[AntAlmanac Class Notification] Class opened"
_WAIT_SUBJECT = "[AntAlmanac Class Notification] Class waitlisted"
_CNCL_SUBJECT = "[AntAlmanac Class Notification] Class cancelled"

_CHUNK_SAFE = 900
_CHUNK_OPTIMIZED = -1

# EXCEPTIONS

class HttpResponseError(Exception):
    def __init__(self, message):
        super().__init__(message)

# FUNCTIONS

def fetch_notification_codes(debug: bool=False) -> dict:
    """
        Fetches all codes to check for notification status

        Args
            debug: flag to enable debugging code

        Return
            dictionary of course codes
            {
                'code' : {
                    'email' : [emails...],
                    'sms' : [numbers...],
                    'name' : 'class name'
                }
            }
    """
    raise NotImplementedError

def chunk_codes(codes: list, optimize: bool=False, debug: bool=False):
    """
        Chunks codes into ranges compatiable with websoc

        currently only chunks into ranges of 900 max
        TODO: build analysis tool for websoc to find optimized chunking range

        Args
            codes: list of course codes to chunk, codes should be sorted from min to max
            optimize: TODO: optimize flag for wider range than 900

        Return
            nested lists of code chunks
            [ [1, 2, 3, 4], [7, 10, 24], ... ]
    """
    chunks = []

    start = None
    end = None
    for idx, code in enumerate(codes):
        if debug: print()
        if start is None:
            end = start = (idx, code)
            if debug: print('Starting', start, end)
            # continue
        elif code - start[1] <= _CHUNK_SAFE:
            end = (idx, code)
            if debug: print('New end', end)
            # continue
        else:
            if debug: print('Chunking', codes[start[0]:idx])
            chunks.append(codes[start[0]:idx])
            start = end = (idx, code)
        print(start, end)

    # capture final chunk if not caught by for loop
    if end[0] == len(codes) - 1:
        chunks.append(codes[start[0]:end[0] + 1])
    
    return chunks

def fetch_websoc(params: dict, debug: bool=False) -> BeautifulSoup:
    """
        Fetchs a websoc live page
        Args
            params: parameters to encode in the url
            example
            {
                'YearTerm' : '2019-92',
                'CourseCodes' :'30000-32000',
                'CancelledCourses' : 'Include',
                'Submit' : 'XML'
            }
        
        Raises
            HttpResponseError: GET return status code >= 400

        Returns
            a BeautifulSoup object
    """
    begin_rsp = time.time()
    rsp = requests.get(_WEBSOC, params=params)

    if rsp.status_code < 300 and debug:
        print(f'>>> Response code: {rsp.status_code}')
    elif rsp.status_code >= 300 and rsp.status_code < 400 and debug:
        print(f'>>> Redirection: {rsp.status_code}')
    elif rsp.status_code >= 400:
        raise HttpResponseError(f'Websoc status code {rsp.status_code}')

    if debug: print(rsp)

    soup = BeautifulSoup(rsp.content, 'lxml')

    end_rsp = time.time()

    if debug: print_time(begin_rsp, end_rsp, '>>> Fetch websoc time:')
    return soup

def fetch_code_statuses(chunks: list, debug: bool=False):
    """
        Fetches the status of all codes
        TODO: look into fetching all chunks asynchronously and then merging the sets

        Args:
            chunked_codes: nested listof chunked codes
                [ [1, 2, 3, 4], [7, 10, 24], ...]

        Return
            TODO: look into using a set instead of a list
            dictionary of statuses and their codes as a list
            {
                'status' : [codes]
            }
    """
    begin = time.time()
    statuses = defaultdict(list)

    for chunk in chunks:
        if debug: print('Chunk:', chunk)
        params = {
            'YearTerm' : _TERM,
            'CourseCodes' : f'{chunk[0]}-{chunk[len(chunk) - 1]}',
            'CancelledCourses' : 'Include',
            'Submit' : 'XML'
        }
        begin_rsp = time.time()
        ######## OLD ##########
        # rsp = requests.get(_WEBSOC, params=params)
        # end_rsp = time.time()
        
        # if debug: 
        #     print(rsp)
        #     print_time(begin_rsp, end_rsp, '>>> Get response time:')
        # soup = BeautifulSoup(rsp.content, 'lxml')
        #######################
        try:
            soup = fetch_websoc(params)
        except HttpResponseError as e:
            print(e)
            print('ERROR: chunk request failed', file=sys.stderr)
            continue
        # if debug: print(soup)

        begin_it = time.time()
        for item in soup.find_all('section'):
            cc = item.find('course_code').text
            # if debug: print(cc)
            if int(cc) in chunk:
                status = item.find('sec_status').text
                if debug: print(f'Chunk({cc}): ', status)
                statuses[status].append(cc)
        end_it = time.time()
        print_time(begin_it, end_it, '>>> Iteration time:')

    end = time.time()
    if debug: print_time(begin, end, '>>> Fetch status time:')
    return statuses

async def dispatch(statuses: dict, notification_codes: dict, debug: bool=False) -> set:
    """
        Takes each status and builds a dispatcher

        Args
            statuses: dictionary of all statuses
            {

            }

            notification_codes: dictionary of the codes and their related information
            {

            }

        Return
            set of all dispatched codes
            {codes, ...}
    """
    tasks = []
    for status in statuses:
        if status.lower() != 'open':
            continue

        temp = defaultdict(dict)

        for code in statuses[code]:
            temp[code] = notification_codes[code]
        
        tasks.append(send_emails(temp, status))
    await asyncio.gather(*tasks)
    # TODO: Return completed notifications, unions sets of dispatched codes
    return statuses['OPEN']


def format_content(status: str, name: str, code: str) -> str:
    """
        simply used to format the message content for an email based on status

        Args
            status: status of the course
            name: name of the course
            code: code of the course

        Return
            string content for the body of the email
    """
    if status == 'OPEN':
        msg = f'Space opened in {name}. Code: {code}'
    if status == 'Waitl':
        msg = f'Waitlist opened for {name}. Code: {code}'
    return f"""
    Hello User,
    {msg}
    """

async def send_emails(mail_list: dict, status: str):
    """
        sends emails out for a specific status using gmail smtp
        
        Args:
            mail_list: dict of codes mapped to emails and names
            {
                'code' : {
                    email : [],
                    name : 'class'
                },
                ...
            }
            status: status of the codes in the mailing list
    """
    _FROM = 'antalmanac@gmail.com'

    _MESSAGES = []
    for code, info in mail_list.items():
        msg = EmailMessage()
        msg.set_content(format_content(status, info['name'], code)) 
        msg['To'] = secret._EMAIL_USERNAME
        msg['From'] = _FROM

        if status == 'OPEN':
            msg['Subject'] = _OPEN_SUBJECT
        elif status == 'Waitl':
            msg['Subject'] = _WAIT_SUBJECT

        msg['Bcc'] = ','.join(info['email'])
        _MESSAGES.append(msg)

    server = aiosmtplib.SMTP(
        hostname='smtp.gmail.com',
        port=587,
        start_tls=True,
        username=secret._EMAIL_USERNAME,
        password=secret._EMAIL_PASSWORD
    )

    await server.connect()
    tasks = [server.send_message(msg) for msg in _MESSAGES]
    await asyncio.gather(*tasks)
    await server.quit()    

# Not started
async def send_text_messages(phone_list: dict, status: str):
    """
        Sends text messages
    """
    raise NotImplementedError

def remove_registered_notifications(completed_codes: set, debug: bool=False) -> None:
    """
        Accesses the database and removes all the data for a completed notification dispatch

        Args
            completed_notifications: dictionary of codes and related information to remove due to successful dispatch
    """
    raise NotImplementedError

def print_time(begin, end, msg):
    elapsed = f'{(end - begin):.4f}'
    print(f'{msg:<30}: {elapsed:<12}')

# MAIN

def main():
    while True:
        notification_codes = fetch_notification_codes()
        chunks = chunk_codes(list(notification_codes).sort)
        statuses = fetch_code_statuses(chunks)

        completed_notifications = dispatch(statuses, notification_codes)

        remove_registered_notifications(completed_notifications)

if __name__ == '__main__':
    main()
    