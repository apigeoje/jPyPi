#!/usr/bin/python

import httplib
import httplib2
import os
import random
import requests
import sys
import threading
import time

from apiclient.discovery import build
from apiclient.errors import HttpError
from apiclient.http import MediaFileUpload
from oauth2client.client import flow_from_clientsecrets
from oauth2client.file import Storage
from oauth2client.tools import argparser, run_flow
from string import Template

# Explicitly tell the underlying HTTP transport library not to retry, since
# we are handling retry logic ourselves.
httplib2.RETRIES = 1

# Maximum number of times to retry before giving up.
MAX_RETRIES = 10

# Always retry when these exceptions are raised.
RETRIABLE_EXCEPTIONS = (httplib2.HttpLib2Error, IOError, httplib.NotConnected,
  httplib.IncompleteRead, httplib.ImproperConnectionState,
  httplib.CannotSendRequest, httplib.CannotSendHeader,
  httplib.ResponseNotReady, httplib.BadStatusLine)

# Always retry when an apiclient.errors.HttpError with one of these status
# codes is raised.
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]

CLIENT_SECRETS_FILE = PATH_TO_CLIENT_SECRETS
MISSING_CLIENT_SECRETS_MESSAGE = "Missing client secrets message"
# This OAuth 2.0 access scope allows an application to upload files to the
# authenticated user's YouTube channel, but doesn't allow other types of access.
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"


YOUTUBE_PRIVACY_STATUS = 'unlisted' # can also be 'public' or 'unlisted'
YOUTUBE_CATEGORY_ID = '22' # video
YOUTUBE_DESCRIPTION_TEMPLATE = "This is a video of $who on $when. \n\n\
            It was filmed $where by $filmer."

JBABYMON_TAG = ['movement']
msg = {}
jEvent = {}

class jYouTubeUploader(threading.Thread):
    '''
        This class provides a simple interface to upload files
        to youtube.

        It is intended to work on the raspberry pi in conjunction
        with a video recording process.

        It receives the filename which should be any acceptable
        command line path i.e., file, ./file, /full/path/to/file

        Also it receives metadata for posting with the video.
        The format of this data is determined by the
        DESCRIPTION_TEMPLATE above. every $ variable must have a
        corresponding element in the metadata object
    '''

    def __init__(self, filename, metadata, args):
        threading.Thread.__init__(self)
        if not filename and not args.file:
            raise ValueError("Please specify a valid filename")
	elif not args.file:
	    self.filename = filename
        else: 
            self.filename = args.file

        if args.title:
            self.title = args.title
        else:
            title = self.filename.split('/')
            self.title = title[len(title)-1]

        self.body = dict(
                        snippet=dict(
                            title=self.title,
                            description=Template(YOUTUBE_DESCRIPTION_TEMPLATE).substitute(metadata),
                            tags=JBABYMON_TAG,
                            categoryId=YOUTUBE_CATEGORY_ID
                        ),
                        status=dict(
                            privacyStatus=YOUTUBE_PRIVACY_STATUS
                        )
                    )

        self.youtube = self.get_authenticated_service(args)
        

    def run(self):

        try:
        # Call the API's videos.insert method to create and upload the video.
            self.insert_request = self.youtube.videos().insert(
              part=",".join(self.body.keys()),
              body=self.body,
            # The chunksize parameter specifies the size of each chunk of data, in
            # bytes, that will be uploaded at a time. Set a higher value for
            # reliable connections as fewer chunks lead to faster uploads. Set a lower
            # value for better recovery on less reliable connections.
            #
            # Setting "chunksize" equal to -1 in the code below means that the entire
            # file will be uploaded in a single HTTP request. (If the upload fails,
            # it will still be retried where it left off.) This is usually a best
            # practice, but if you're using Python older than 2.6 or if you're
            # running on App Engine, you should set the chunksize to something like
            # 1024 * 1024 (1 megabyte).
              media_body=MediaFileUpload(self.filename, chunksize=-1, resumable=True)
            )

            self.resumable_upload(self.insert_request)

        except HttpError, e:
            msg['error'] = e
            print msg['error']



    def get_authenticated_service(self, args):

        self.flow = flow_from_clientsecrets(CLIENT_SECRETS_FILE,
          message=MISSING_CLIENT_SECRETS_MESSAGE,
          scope=YOUTUBE_UPLOAD_SCOPE)

        self.storage = Storage("%s-oauth2.json" % sys.argv[0])
        self.credentials = self.storage.get()

        if self.credentials is None or self.credentials.invalid:
          flags = argparser.parse_args()
          self.credentials = run_flow(self.flow, self.storage, flags)

        return build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION,
          http=self.credentials.authorize(httplib2.Http()))


    # This method implements an exponential backoff strategy to resume a
    # failed upload.
    def resumable_upload(self, insert_request):
        response = None
        error = None
        retry = 0
        while response is None:
            try:
                #print "Uploading file..."
                status, response = insert_request.next_chunk()
                if response is not None:
                    if 'id' in response:
                        print response['id']
                    else:
                        sys.exit("The upload failed with an unexpected response: %s" % response)
            except HttpError, e:
                if e.resp.status in RETRIABLE_STATUS_CODES:
                    error = "A retriable HTTP error %d occurred:\n%s" % (e.resp.status,
                                                                 e.content)
                else:
                    raise
            except RETRIABLE_EXCEPTIONS, e:
                error = "A retriable error occurred: %s" % e

        if error is not None:
            retry += 1
            if retry > MAX_RETRIES:
                sys.exit("No longer attempting to retry.")

            max_sleep = 2 ** retry
            sleep_seconds = random.random() * max_sleep
            #"Sleeping %f seconds and then retrying..." % sleep_seconds
            time.sleep(sleep_seconds)
    

if __name__ == '__main__':
    argparser.add_argument("--file", required=True, help="Video file to upload")
    argparser.add_argument("--title", help="Video title", default=None)
    argparser.add_argument("--description", help="Video description",
                 default="Test Description")
    argparser.add_argument("--category", default="22",
                 help="Numeric video category. " +
                 "See https://developers.google.com/youtube/v3/docs/videoCategories/list")
    argparser.add_argument("--keywords", help="Video keywords, comma separated",
                 default="")
    argparser.add_argument("--privacyStatus", 
                 default=YOUTUBE_PRIVACY_STATUS, help="Video privacy status.")
    args = argparser.parse_args()
    meta = dict(who="BDo",when=int(time.time()), where="here",filmer="Bob")

    upl = jYouTubeUploader(None, meta, args)
    upl.start()
    upl.join()
