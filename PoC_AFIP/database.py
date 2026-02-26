import os
from datetime import datetime
from pathlib import Path
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

# Configuración de Ruta Absoluta para evitar múltiples archivos .db
BASE_DIR = Path(__file__).parent
DATABASE_PATH = BASE_DIR / "mock_database.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

engine = create_engine(DATABASE_URL, echo=False)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

class Orden(Base):
    """Representa una orden de venta de MeLi o Manual."""
    __tablename__ = "ordenes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_name = Column(String(100), nullable=False)
    total_amount = Column(Float, nullable=False)
    # Evita duplicados y vincula con la API
    meli_order_id = Column(String(50), unique=True, nullable=True)
    shipping_type = Column(String(20), default="NORMAL") # FULL, MADRYN, etc
    status = Column(String(20), default="PENDIENTE")    # FACTURADA, ERROR, PENDIENTE
    error_message = Column(String(255), nullable=True)

    factura = relationship("Factura", back_populates="orden", uselist=False)

    def __repr__(self):
        return f"<Orden id={self.id} meli_id={self.meli_order_id} cliente='{self.client_name}'>"

class Factura(Base):
    """Datos fiscales vinculados a la orden."""
    __tablename__ = "facturas"
    id = Column(Integer, primary_key=True, autoincrement=True)
    orden_id = Column(Integer, ForeignKey("ordenes.id"), nullable=False)
    cae = Column(String(14), nullable=False)
    cae_expiration = Column(String(10), nullable=False)   # formato YYYYMMDD
    created_at = Column(DateTime, default=datetime.utcnow)
    orden = relationship("Orden", back_populates="factura")

    def __repr__(self):
        return f"<Factura id={self.id} CAE={self.cae}>"

def init_db():
    Base.metadata.create_all(bind=engine)
    print(f"[DB] Base de datos inicializada en: {DATABASE_PATH}")

if __name__ == "__main__":
    init_db()