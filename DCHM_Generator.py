from qgis.PyQt.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QAction,
    QDoubleSpinBox,
    QCheckBox,
)
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsRasterLayer, QgsVectorLayer, QgsProject, QgsMessageLog
from osgeo import gdal, osr
import numpy as np
import os


class DCHM_Generator:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dsm = None
        self.dtm = None
        self.points = None
        self.dsmComboBox = None
        self.dtmComboBox = None
        self.pointsComboBox = None
        self.despikeCheckBox = None
        self.despikeThresholdSpin = None
        self.plugin_dir = os.path.dirname(__file__)

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        self.action = QAction(
            QIcon(icon_path),
            "DCHM生成",
            self.iface.mainWindow()
        )
        self.action.triggered.connect(self.showWidget)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("DCHM生成", self.action)

    def unload(self):
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginMenu("DCHM生成", self.action)

    def showWidget(self):
        self.widget = QWidget()
        layout = QVBoxLayout()

        # DSM選択
        layout.addWidget(QLabel("DSMレイヤを選択"))
        self.dsmComboBox = QComboBox()
        layout.addWidget(self.dsmComboBox)

        # DTM選択
        layout.addWidget(QLabel("DTMレイヤを選択"))
        self.dtmComboBox = QComboBox()
        layout.addWidget(self.dtmComboBox)

        # ポイントレイヤ選択
        layout.addWidget(QLabel("露出点(検証点)レイヤを選択"))
        self.pointsComboBox = QComboBox()
        layout.addWidget(self.pointsComboBox)

        # レイヤ取得
        layers = QgsProject.instance().mapLayers().values()
        for l in layers:
            if isinstance(l, QgsRasterLayer):
                self.dsmComboBox.addItem(l.name())
                self.dtmComboBox.addItem(l.name())
            elif isinstance(l, QgsVectorLayer):
                self.pointsComboBox.addItem(l.name())

        # デスパイク処理 有効/無効
        self.despikeCheckBox = QCheckBox("スパイク除去を有効にする(外れ値のみ補正)")
        self.despikeCheckBox.setChecked(True)
        layout.addWidget(self.despikeCheckBox)

        # デスパイク閾値 (m)
        layout.addWidget(QLabel("スパイク閾値 (m) - 値を大きくすると樹頂点をより保持する"))
        self.despikeThresholdSpin = QDoubleSpinBox()
        self.despikeThresholdSpin.setRange(0.5, 20.0)
        self.despikeThresholdSpin.setSingleStep(0.5)
        self.despikeThresholdSpin.setValue(5.0)
        layout.addWidget(self.despikeThresholdSpin)

        # デスパイク窓サイズ (物理サイズ指定。解像度が変わっても同じ物理範囲を評価する)
        layout.addWidget(QLabel("スパイク除去の窓サイズ (m) - 中央値フィルタの評価範囲(物理サイズ)"))
        self.despikeWindowSpin = QDoubleSpinBox()
        self.despikeWindowSpin.setRange(0.25, 5.0)
        self.despikeWindowSpin.setDecimals(2)
        self.despikeWindowSpin.setSingleStep(0.25)
        self.despikeWindowSpin.setValue(0.75)
        layout.addWidget(self.despikeWindowSpin)

        # 解像度 (m) — 施業前後で必ず同じ値を使うこと
        layout.addWidget(QLabel("出力解像度 (m) - 同一現場の施業前後比較では必ず同じ値を使用すること"))
        self.resolutionSpin = QDoubleSpinBox()
        self.resolutionSpin.setRange(0.01, 5.0)
        self.resolutionSpin.setDecimals(3)
        self.resolutionSpin.setSingleStep(0.01)
        self.resolutionSpin.setValue(0.1)
        layout.addWidget(self.resolutionSpin)

        # 出力先CRS (EPSGコード) — DSM/DTMの元CRSが何であっても、
        # ここで指定したCRSへ「再投影とグリッド整列を1回のWarpで同時に」行う。
        # QGIS側で事前に再投影してから読み込むと、ここでのWarpと合わせて
        # 2回リサンプルされ画質(樹冠ピーク)が余分に劣化するため非推奨。
        # 元の生データ(ドローン写真測量ソフトの出力そのまま)を読み込むこと。
        layout.addWidget(QLabel("出力先CRS EPSGコード - 元データは再投影せずそのまま読み込むこと(二重リサンプル防止)"))
        self.targetCrsEdit = QComboBox()
        self.targetCrsEdit.setEditable(True)
        # 日本の一般的なCRS: 旧JGD2000系と新JGD2011系(平面直角座標系)
        crs_list = [
            "EPSG:6676",  # JGD2011 / Japan Plane Rectangular CS IX (Hokkaido)
            "EPSG:6677",  # JGD2011 / Japan Plane Rectangular CS X
            "EPSG:6678",  # JGD2011 / Japan Plane Rectangular CS XI (Honshu)
            "EPSG:6679",  # JGD2011 / Japan Plane Rectangular CS XII
            "EPSG:6680",  # JGD2011 / Japan Plane Rectangular CS XIII
            "EPSG:6681",  # JGD2011 / Japan Plane Rectangular CS XIV
            "EPSG:6682",  # JGD2011 / Japan Plane Rectangular CS XV
            "EPSG:6683",  # JGD2011 / Japan Plane Rectangular CS XVI
            "EPSG:6684",  # JGD2011 / Japan Plane Rectangular CS XVII
            "EPSG:6685",  # JGD2011 / Japan Plane Rectangular CS XVIII
            "EPSG:2443",  # JGD2000 / Japan Plane Rectangular CS IX
            "EPSG:2444",  # JGD2000 / Japan Plane Rectangular CS X
            "EPSG:2445",  # JGD2000 / Japan Plane Rectangular CS XI
            "EPSG:2446",  # JGD2000 / Japan Plane Rectangular CS XII
        ]
        self.targetCrsEdit.addItems(crs_list)
        self.targetCrsEdit.setCurrentText("EPSG:6676")
        layout.addWidget(self.targetCrsEdit)

        # 出力後、プロジェクトに追加するかどうか
        self.addToProjectCheckBox = QCheckBox("生成完了後、プロジェクトに自動追加")
        self.addToProjectCheckBox.setChecked(True)
        layout.addWidget(self.addToProjectCheckBox)

        # DCHM生成ボタン
        btn = QPushButton("DCHMを生成")
        btn.clicked.connect(self.generateDCHM)
        layout.addWidget(btn)

        self.widget.setLayout(layout)
        self.widget.setWindowTitle("DCHM生成ツール")
        self.widget.show()

    def despike(self, arr, threshold_m, window_m, resolution_m):
        """
        単純なmedian_filterによる全画素置換ではなく、
        局所中央値との差がthreshold_mを超えるピクセルのみを
        中央値で補正する。樹頂点のような自然な鋭いピークは
        threshold_m以下であれば保持される。

        window_m: 中央値を取る窓の物理サイズ(m)。画素数(size)は
        解像度(resolution_m)から都度計算するため、DSMの出力解像度が
        現場ごとに変わっても評価範囲が一定に保たれる。
        """
        import scipy.ndimage as ndimage
        size = max(3, int(round(window_m / resolution_m)))
        if size % 2 == 0:
            size += 1  # median_filterは奇数サイズが望ましい
        median = ndimage.median_filter(arr, size=size)
        diff = np.abs(arr - median)
        spike_mask = diff > threshold_m
        result = arr.copy()
        result[spike_mask] = median[spike_mask]
        return result

    def generateDCHM(self):
        if not (self.dsmComboBox and self.dtmComboBox):
            QMessageBox.warning(None, "エラー", "先にDSMとDTMのレイヤを選択してください。")
            return

        # === レイヤ取得 ===
        dsm_name = self.dsmComboBox.currentText()
        dtm_name = self.dtmComboBox.currentText()
        points_name = self.pointsComboBox.currentText() if self.pointsComboBox else None

        self.dsm = QgsProject.instance().mapLayersByName(dsm_name)[0]
        self.dtm = QgsProject.instance().mapLayersByName(dtm_name)[0]
        self.points = QgsProject.instance().mapLayersByName(points_name)[0] if points_name else None

        despike_enabled = self.despikeCheckBox.isChecked() if self.despikeCheckBox else True
        despike_threshold = self.despikeThresholdSpin.value() if self.despikeThresholdSpin else 5.0
        despike_window_m = self.despikeWindowSpin.value() if hasattr(self, "despikeWindowSpin") and self.despikeWindowSpin else 0.75
        target_res = self.resolutionSpin.value() if hasattr(self, "resolutionSpin") and self.resolutionSpin else 0.1
        target_crs_str = self.targetCrsEdit.currentText().strip() if hasattr(self, "targetCrsEdit") and self.targetCrsEdit else "EPSG:6676"

        # === 出力先選択 ===
        out_path, _ = QFileDialog.getSaveFileName(None, "DCHMを保存", os.path.expanduser("~"), "GeoTIFF (*.tif)")
        if not out_path:
            return

        # === GDALでラスタ開く ===
        dsm_ds = gdal.Open(self.dsm.dataProvider().dataSourceUri())
        dtm_ds = gdal.Open(self.dtm.dataProvider().dataSourceUri())

        if dsm_ds is None or dtm_ds is None:
            QMessageBox.critical(None, "エラー", "DSMまたはDTMラスタを開けませんでした。")
            return

        # === 目的CRSの設定 ===
        target_srs = osr.SpatialReference()
        if target_srs.SetFromUserInput(target_crs_str) != 0:
            QMessageBox.critical(None, "エラー", f"CRS指定が不正です: {target_crs_str}")
            return
        target_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        target_wkt = target_srs.ExportToWkt()

        # === 範囲計算 (元ラスタの座標を目的CRSへ変換してから重複域を算出) ===
        # DSM/DTMが元々別々のCRS、あるいはQGIS上で個別に再投影されたもので
        # あっても、ここで必ず同じ目的CRSの上で重複域を計算するため、
        # 入力側の再投影履歴に依存しない。
        def get_extent_in_target_crs(ds):
            gt = ds.GetGeoTransform()
            src_srs = osr.SpatialReference()
            src_srs.ImportFromWkt(ds.GetProjection())
            src_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            xs = (gt[0], gt[0] + ds.RasterXSize * gt[1])
            ys = (gt[3], gt[3] + ds.RasterYSize * gt[5])
            corners = [(xs[0], ys[0]), (xs[0], ys[1]), (xs[1], ys[0]), (xs[1], ys[1])]
            if not src_srs.IsSame(target_srs):
                transform = osr.CoordinateTransformation(src_srs, target_srs)
                corners = [transform.TransformPoint(x, y)[:2] for x, y in corners]
            xs_t = [c[0] for c in corners]
            ys_t = [c[1] for c in corners]
            return (min(xs_t), max(xs_t), min(ys_t), max(ys_t))

        dsm_ext = get_extent_in_target_crs(dsm_ds)
        dtm_ext = get_extent_in_target_crs(dtm_ds)

        overlap_xmin = max(dsm_ext[0], dtm_ext[0])
        overlap_xmax = min(dsm_ext[1], dtm_ext[1])
        overlap_ymin = max(dsm_ext[2], dtm_ext[2])
        overlap_ymax = min(dsm_ext[3], dtm_ext[3])

        if overlap_xmin >= overlap_xmax or overlap_ymin >= overlap_ymax:
            QMessageBox.critical(None, "エラー", "DSMとDTMに重複する範囲がありません。")
            return

        # === 目的CRSへの再投影 + 絶対グリッドへの整列を1回のWarpで同時に行う ===
        # dstSRSを明示指定することで「事前にQGISで再投影 → さらにここでWarp」という
        # 二重リサンプルを避ける。元データ(ドローン写真測量ソフトの出力そのまま、
        # 元のCRSのまま)を直接読み込むこと。
        # targetAlignedPixels=True により、出力原点は解像度の整数倍の絶対グリッドに
        # スナップされるため、DSM/DTMそれぞれの元の画素位相(サブピクセルのズレ)が
        # 施業前後でどうであっても、最終出力の原点は同一解像度である限り必ず一致する。
        def warp_to_grid(ds, xmin, xmax, ymin, ymax, res, nodata_out):
            src_nd = ds.GetRasterBand(1).GetNoDataValue()
            opts = gdal.WarpOptions(
                format="MEM",
                dstSRS=target_wkt,
                outputBounds=(xmin, ymin, xmax, ymax),
                xRes=res,
                yRes=res,
                targetAlignedPixels=True,
                resampleAlg=gdal.GRA_Bilinear,
                srcNodata=src_nd,
                dstNodata=nodata_out,
                multithread=True,
            )
            return gdal.Warp("", ds, options=opts)

        NODATA = -9999.0
        dsm_aligned = warp_to_grid(dsm_ds, overlap_xmin, overlap_xmax, overlap_ymin, overlap_ymax, target_res, NODATA)
        dtm_aligned = warp_to_grid(dtm_ds, overlap_xmin, overlap_xmax, overlap_ymin, overlap_ymax, target_res, NODATA)

        if dsm_aligned is None or dtm_aligned is None:
            QMessageBox.critical(None, "エラー", "DSM/DTMのグリッド整列(gdal.Warp)に失敗しました。")
            return

        # DSMとDTMのWarp結果は同じoutputBounds/xRes/yRes/targetAlignedPixelsから
        # 生成されているため、ジオトランスフォームは完全に一致する。
        out_gt = dsm_aligned.GetGeoTransform()
        w = dsm_aligned.RasterXSize
        h = dsm_aligned.RasterYSize

        dsm_band = dsm_aligned.GetRasterBand(1).ReadAsArray().astype(np.float32)
        dtm_band = dtm_aligned.GetRasterBand(1).ReadAsArray().astype(np.float32)

        # === スパイク除去 (閾値超のピクセルのみ補正、樹頂点の自然なピークは保持) ===
        if despike_enabled:
            dsm_band = self.despike(
                dsm_band,
                threshold_m=despike_threshold,
                window_m=despike_window_m,
                resolution_m=target_res,
            )

        # === マスク作成 ===
        mask = (dsm_band != NODATA) & (dtm_band != NODATA)

        # === 面補正 (トレンド面) ===
        correction_map = np.zeros((h, w), dtype=np.float32)
        if self.points and self.points.featureCount() >= 3:
            A_list, B_list = [], []
            for f in self.points.getFeatures():
                pt = f.geometry().asPoint()
                c = int((pt.x() - out_gt[0]) / out_gt[1])
                r = int((pt.y() - out_gt[3]) / out_gt[5])
                if 0 <= r < h and 0 <= c < w and mask[r, c]:
                    A_list.append([pt.x(), pt.y(), 1])
                    B_list.append(dsm_band[r, c] - dtm_band[r, c])

            if len(A_list) >= 3:
                coeff, _, _, _ = np.linalg.lstsq(A_list, B_list, rcond=None)
                X_coords = out_gt[0] + (np.arange(w) + 0.5) * out_gt[1]
                Y_coords = out_gt[3] + (np.arange(h) + 0.5) * out_gt[5]
                X_mesh, Y_mesh = np.meshgrid(X_coords, Y_coords)
                correction_map = (coeff[0] * X_mesh + coeff[1] * Y_mesh + coeff[2]).astype(np.float32)

        # === DCHM 計算 ===
        dchm = np.zeros((h, w), dtype=np.float32)
        dchm[mask] = dsm_band[mask] - dtm_band[mask] - correction_map[mask]
        dchm[dchm < 0] = 0
        dchm[~mask] = NODATA

        # === 保存処理 ===
        driver = gdal.GetDriverByName("GTiff")
        out_ds = driver.Create(out_path, w, h, 1, gdal.GDT_Float32)
        out_ds.SetGeoTransform(out_gt)
        out_ds.SetProjection(target_wkt)
        out_ds.GetRasterBand(1).WriteArray(dchm)
        out_ds.GetRasterBand(1).SetNoDataValue(NODATA)
        out_ds.FlushCache()
        out_ds = None

        # === プロジェクトに追加 ===
        add_to_project = self.addToProjectCheckBox.isChecked() if hasattr(self, "addToProjectCheckBox") and self.addToProjectCheckBox else False
        if add_to_project:
            layer = QgsRasterLayer(out_path, os.path.splitext(os.path.basename(out_path))[0])
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
            else:
                QMessageBox.warning(None, "警告", "DCHMファイルは生成されましたが、プロジェクトへの追加に失敗しました。")

        QMessageBox.information(
            None, "完了",
            f"DCHMを生成しました: {out_path}\n原点=({out_gt[0]:.4f}, {out_gt[3]:.4f}), 解像度={target_res}m"
        )
