##!/usr/bin/env python
# encoding: utf-8
#
# Copyright 2013 Rodrigo Ancavil del Pino
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
import tornado.ioloop
import tornado.web
import xml.dom.minidom
import inspect
import re
import json

from pyrestful import mediatypes, types


class PyRestfulException(Exception):
    """ Class for PyRestful exceptions """
    def __init__(self,message):
        self.message = message
    def __str__(self):
        return repr(self.message)

def config(func,method,**kwparams):
    """ Decorator config function """
    path     = None
    produces = None
    consumes = None
    types    = None

    if len(kwparams):
        path = kwparams['_path']
        if '_produces' in kwparams:
            produces = kwparams['_produces']
        else:
            produces = mediatypes.APPLICATION_JSON
        if '_consumes' in kwparams:
            consumes = kwparams['_consumes']
        if '_types' in kwparams:
            types = kwparams['_types']

    def operation(*args,**kwargs):
        return func(*args,**kwargs)

    operation.func_name       = func.func_name
    operation._func_params    = inspect.getargspec(func).args[1:] # cool
    operation._types          = types or [str]*len(operation._func_params)
    operation._service_name   = re.findall(r"(?<=/)\w+",path) # re.findall("(?<=/)\w+","/var/{hello}/happy") ===> ["var", "happy"]
    operation._service_params = re.findall(r"(?<={)\w+",path)
    operation._method         = method #GET/POST/DELETE/PUT
    operation._produces       = produces
    operation._consumes       = consumes
    operation._query_params   = re.findall(r"(?<=<)\w+",path)
    operation._path           = path

    if not operation._produces in [mediatypes.APPLICATION_JSON,mediatypes.APPLICATION_XML,mediatypes.TEXT_XML]:
        raise PyRestfulException("The media type used do not exist : "+operation.func_name)

    return operation

def get(*params, **kwparams):
    """ Decorator for config a python function like a Rest GET verb	"""
    def method(f):
        return config(f,'GET',**kwparams)
    return method

def post(*params, **kwparams):
    """ Decorator for config a python function like a Rest POST verb	"""
    def method(f):
        return config(f,'POST',**kwparams)
    return method

def put(*params, **kwparams):
    """ Decorator for config a python function like a Rest PUT verb	"""
    def method(f):
        return config(f,'PUT',**kwparams)
    return method

def delete(*params, **kwparams):
    """ Decorator for config a python function like a Rest PUT verb	"""
    def method(f):
        return config(f,'DELETE',**kwparams)
    return method


class RestHandler(tornado.web.RequestHandler):

    def get(self):
        """ Executes get method """
        self._exe('GET')

    def post(self):
        """ Executes post method """
        self._exe('POST')

    def put(self):
        """ Executes put method"""
        self._exe('PUT')

    def delete(self):
        """ Executes put method"""
        self._exe('DELETE')

    def _exe(self, method):
        """ Executes the python function for the Rest Service """
        request_path = self.request.path
        path = request_path.split('/')
        services_and_params = filter(lambda x: x!='',path)

        # Get all funcion names configured in the class RestHandler
        functions    = filter(lambda op: hasattr(getattr(self,op),'_service_name') == True and inspect.ismethod(getattr(self,op)) == True, dir(self))
        # Get all http methods configured in the class RestHandler
        http_methods = map(lambda op: getattr(getattr(self,op),'_method'), functions)

        if method not in http_methods:
            raise tornado.web.HTTPError(405,'The service not have %s verb'%method)

        for operation in map(lambda op: getattr(self,op), functions):
            service_name          = getattr(operation, "_service_name")
            service_params        = getattr(operation, "_service_params")
            # If the _types is not specified, assumes str types for the params
            params_types          = getattr(operation,"_types") or [str]*len(service_params)
            params_types          = map(lambda x,y : y if x is None else x, params_types, [str]*len(service_params))
            # produces              = getattr(operation,"_produces")
            services_from_request = filter(lambda x: x in path,service_name)
            # query_params          = getattr(operation,"_query_params")

            # FIXME 为了兼容motor的异步调用逻辑，这里hack了部分pyrestful的代码
            if operation._method == self.request.method and service_name == services_from_request and len(service_params) + len(service_name) == len(services_and_params):
                try:
                    params_values = self._find_params_value_of_url(service_name,request_path) + self._find_params_value_of_arguments(operation)
                    p_values      = self._convert_params_values(params_values, params_types)
                    response      = operation(*p_values)

                except Exception as detail:
                    raise tornado.web.HTTPError(500,"Internal Server Error : %s"%detail)

    def _find_params_value_of_url(self,services,url):
        """ Find the values of path params """
        values_of_query = list()
        url_split = url.split("/")
        values = [item for item in url_split if item not in services and item != '']
        for v in values:
            if v != None:
                values_of_query.append(v)
        return values_of_query

    def _find_params_value_of_arguments(self, operation):
        values = []

        if len(self.request.arguments) > 0:

            service_params = operation._service_params
            func_params = operation._func_params

            # order matter??
            params = [item for item in func_params if item not in service_params]
            for p in params:
                if p in self.request.arguments.keys():
                    v = self.request.arguments[p]
                    values.append(v[0]) # FIXME what about if the value is a list
                else:
                    values.append(None)
        elif len(self.request.arguments) == 0 and len(operation._query_params) > 0:
            values = [None]*(len(operation._func_params) - len(operation._service_params))

        return values

    def _convert_params_values(self, values_list, params_types):
        """ Converts the values to the specifics types """
        values = list()
        i = 0
        for v in values_list:
            if v != None:
                values.append(types.convert(v,params_types[i]))
            else:
                values.append(v)
            i+=1
        return values

    @classmethod
    def get_services(self):
        """ Generates the resources (uri) to deploy the Rest Services """
        services = []
        for f in dir(self):
            o = getattr(self,f)
            if callable(o) and hasattr(o,'_service_name'):
                services.append(getattr(o,'_service_name'))
        return services

    @classmethod
    def get_paths(self):
        """ Generates the resources from path (uri) to deploy the Rest Services """
        paths = []
        for f in dir(self):
            o = getattr(self,f)
            if callable(o) and hasattr(o,'_path'):
                paths.append(getattr(o,'_path'))
        return paths


class RestService(tornado.web.Application):
    """ Class to create Rest services in tornado web server """
    resource = None
    def __init__(self, rest_handlers, resource=None, handlers=None, default_host="", transforms=None, wsgi=False, **settings):
        restservices = []
        self.resource = resource
        for r in rest_handlers:
            svs = self._generateRestServices(r)
            restservices += svs
        if handlers != None:
            restservices += handlers
        super(RestService, self).__init__(restservices, default_host, transforms, wsgi, **settings)

    def _generateRestServices(self,rest):
        svs = []
        paths = rest.get_paths()

        # 针对tornado路由规则做的一些hack
        for p in paths:
            s = re.sub(r"(?<={)\w+}",".*",p).replace("{","")
            o = re.sub(r"(?<=<)\w+","",s).replace("<","").replace(">","").replace("&","").replace("?","")
            svs.append((o,rest,self.resource))

        return svs
