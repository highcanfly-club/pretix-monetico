#!C:/Python34/python.exe -u
# -*- coding: iso8859-1 -*-

# *****************************************************************************
#
# "Open source" kit for Monetico Paiement(TM)
# 
# File "MoneticoPaiement_Ept.py":
# 
# Author   : Euro-Information/e-Commerce
# Version  : 4.0
# Date      : 05/06/2014
# 
# Copyright: (c) 2014 Euro-Information. All rights reserved.
# License  : 
#==============================================================================
#
# "Open source" kit for Monetico Paiement(TM).
# Integration sample in a merchant site for Python
#
# Author   : Euro-Information/e-Commerce
# Version  : 4.0
# Date      : 05/06/2014
#
# Copyright: (c) 2014 Euro-Information. All rights reserved.
#
#==============================================================================
# License:
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#   - Redistributions of source code must retain the above copyright
#     notice and the following disclaimer.
#   - Redistributions in binary form must reproduce the above copyright
#     notice and the following disclaimer in the documentation and/or
#     other materials provided with the distribution.
#   - Neither the name of Euro-Information nor the names of its
#     contributors may be used to endorse or promote products derived
#     from this software without specific prior written permission.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE COPYRIGHT HOLDERS OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE
# GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER
# IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
# OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
# ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# Note: Euro-Information does not provide person-to-person technical
#       support for tryout of Monetico Paiement examples.
#
#==============================================================================
# 
# *****************************************************************************/

import sys, hmac, hashlib


class MoneticoPaiement_Ept :

        def __init__(self, MONETICOPAIEMENT_VERSION, MONETICOPAIEMENT_KEY, MONETICOPAIEMENT_EPTNUMBER, MONETICOPAIEMENT_URLSERVER,MONETICOPAIEMENT_URLPAYMENT,MONETICOPAIEMENT_COMPANYCODE,MONETICOPAIEMENT_URLOK,MONETICOPAIEMENT_URLKO , sLang = "FR") :

                self.sVersion = MONETICOPAIEMENT_VERSION
                self._sCle = MONETICOPAIEMENT_KEY
                self.sNumero = MONETICOPAIEMENT_EPTNUMBER
                self.sUrlPaiement = MONETICOPAIEMENT_URLSERVER + MONETICOPAIEMENT_URLPAYMENT

                self.sCodeSociete = MONETICOPAIEMENT_COMPANYCODE
                self.sLangue = sLang

                self.sUrlOk = MONETICOPAIEMENT_URLOK
                self.sUrlKo = MONETICOPAIEMENT_URLKO



class MoneticoPaiement_Hmac :

        def __init__(self, oEpt):

                self._sUsableKey = self._getUsableKey(oEpt)

        def computeHMACSHA1(self, sData):

                return self.hmac_sha1(self._sUsableKey, sData)

        def hmac_sha1(self, sKey, sData) :

                HMAC = hmac.HMAC(sKey,None,hashlib.sha1)
                #HMAC = hmac.HMAC(sKey,None,sha)
                HMAC.update(sData.encode('iso8859-1'))

                return HMAC.hexdigest()

        def bIsValidHmac(self, sChaine, sMAC):

                return self.computeHMACSHA1(sChaine) == sMAC.lower()
                
        def _getUsableKey(self, oEpt) :

                hexStrKey  = oEpt._sCle[0:38]
                hexFinal   = oEpt._sCle[38:40] + "00";

                cca0=ord(hexFinal[0:1])

                if cca0>70 and cca0<97 :
                        hexStrKey += chr(cca0-23) + hexFinal[1:2]
                elif hexFinal[1:2] == "M" :
                        hexStrKey += hexFinal[0:1] + "0" 
                else :
                        hexStrKey += hexFinal[0:2]

                import encodings.hex_codec
                c =  encodings.hex_codec.Codec()
                hexStrKey = c.decode(hexStrKey)[0]

                return hexStrKey

