CNAE_LOGISTICO_RULES = {
    "alimentos": {
        "keywords": [
            "alimentos",
            "produtos alimentícios",
            "laticínios",
            "frigorífico",
            "padaria",
            "bebidas"
        ],
        "tipo_carga": "paletizada / seca / refrigerada",
        "carrocerias": ["bau", "sider", "refrigerado"],
        "peso_score": 85,
    },
    "autopecas": {
        "keywords": [
            "autopeças",
            "peças e acessórios",
            "componentes automotivos",
            "veículos automotores"
        ],
        "tipo_carga": "industrial / paletizada",
        "carrocerias": ["bau", "sider"],
        "peso_score": 80,
    },
    "materiais_construcao": {
        "keywords": [
            "material de construção",
            "cimento",
            "argamassa",
            "cerâmica",
            "tintas",
            "ferragens"
        ],
        "tipo_carga": "carga seca / paletizada",
        "carrocerias": ["carga seca", "bau", "sider"],
        "peso_score": 75,
    },
    "moveis_madeira": {
        "keywords": [
            "móveis",
            "madeira",
            "esquadrias",
            "serraria"
        ],
        "tipo_carga": "volumosa / seca",
        "carrocerias": ["bau", "sider"],
        "peso_score": 70,
    },
    "metalmecanico": {
        "keywords": [
            "metalúrgica",
            "metalmecânico",
            "usinagem",
            "máquinas",
            "equipamentos industriais"
        ],
        "tipo_carga": "industrial / pesada / paletizada",
        "carrocerias": ["sider", "bau", "carga seca"],
        "peso_score": 78,
    },
    "quimico_permitido": {
        "keywords": [
            "produtos de limpeza",
            "cosméticos",
            "higiene",
            "químicos"
        ],
        "tipo_carga": "industrial / paletizada",
        "carrocerias": ["bau", "sider"],
        "peso_score": 65,
    },
    "atacadista_cd": {
        "keywords": [
            "comércio atacadista",
            "distribuidora",
            "centro de distribuição",
            "operador logístico",
            "armazenagem"
        ],
        "tipo_carga": "carga geral / paletizada",
        "carrocerias": ["bau", "sider", "carga seca"],
        "peso_score": 82,
    },
    "agroindustria": {
        "keywords": [
            "agroindústria",
            "grãos",
            "fertilizantes",
            "rações",
            "sementes",
            "cooperativa"
        ],
        "tipo_carga": "agro / granel / ensacada / paletizada",
        "carrocerias": ["graneleiro", "carga seca", "bau"],
        "peso_score": 76,
    },
}
