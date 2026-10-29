import services.cache as c

print(c.__file__)
print("tem _fontes_para:", hasattr(c, "_fontes_para"))
print("tem _chamar_yfinance:", hasattr(c, "_chamar_yfinance"))
print("tem _salvar_cache:", hasattr(c, "_salvar_cache"))
