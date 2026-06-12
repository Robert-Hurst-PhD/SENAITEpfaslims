# -*- coding: utf-8 -*-
"""EnvironmentalReading content type - RPi temperature/humidity log entry."""
from plone.dexterity.content import Item
from plone.supermodel import model
from zope import schema
from zope.interface import implementer
from senaite.pfas import messageFactory as _


class IEnvironmentalReading(model.Schema):
    """A single temperature/humidity reading from a monitored location.
    Supports Maine CMR Ch.263 continuous-monitoring requirements."""
    location = schema.TextLine(title=_(u"Location"), required=True)
    sensor_id = schema.TextLine(title=_(u"Sensor ID"), required=True)
    temperature_c = schema.Float(title=_(u"Temperature (deg C)"), required=False)
    humidity_pct = schema.Float(title=_(u"Humidity (%)"), required=False)
    reading_time = schema.Datetime(title=_(u"Reading Time"), required=False)
    nist_verified = schema.Bool(title=_(u"NIST-Verified Sensor"),
                                default=False, required=False)
    out_of_range = schema.Bool(title=_(u"Out of Range"),
                               default=False, required=False)


@implementer(IEnvironmentalReading)
class EnvironmentalReading(Item):
    """Environmental reading."""
