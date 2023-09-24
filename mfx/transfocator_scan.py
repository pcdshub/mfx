from epics import caget, caput, camonitor, camonitor_clear
import numpy as np
import matplotlib.pyplot as plt
import time
from scipy.optimize import curve_fit
from IPython import display
#mfx dg1 yag is MFX:DG1:P6740
#mfx dg2 yag is MFX:DG2:P6740
#mfx dg3 yag is MFX:GIGE:02:IMAGE1
#trf_pos=np.linspace(225,230,10)
#range for tfs is 0,300
#trf_align.scan_transfocator(tfs.translation,trf_pos,5)
class gigE_camera_accessor:
    def __init__(self,camera_pv):
        self.camera_pv=camera_pv
        self.get_markers()
        pass
    def get_image(self):
        image = caget(self.camera_pv + ':IMAGE1:ArrayData')#some cameras can be image2 need to consider.
        if len(image) == 0:
            print(" [!] Can't read camera", PV + ".", "Exiting...", '\n')
            sys.exit(1)
        else:
            ArraySizeX = caget(self.camera_pv + ':IMAGE1:ArraySize0_RBV')
            ArraySizeY = caget(self.camera_pv + ':IMAGE1:ArraySize1_RBV')
            image = np.reshape(image, (ArraySizeY, ArraySizeX))
            # image = ndimage.gaussian_filter(image, 0.1) # test gaussian filter denoising
            # image = ndimage.median_filter(image, 1) # test median filter denoising
        return image
    def get_image_roi(self):
        image = self.get_image()
        y_slice = slice(min(self.marker1Y, self.marker2Y), max(self.marker1Y, self.marker2Y))
        x_slice = slice(min(self.marker1X, self.marker2X), max(self.marker1X, self.marker2X))
        image = image[y_slice, x_slice]
        self.active_image=image
        #image = image[self.marker1Y:self.marker2Y, self.marker1X:self.marker2X]
        return image
    def get_markers(self):
        self.marker1X = caget(self.camera_pv + ':Cross1X')
        self.marker1Y = caget(self.camera_pv + ':Cross1Y')
        self.marker2X = caget(self.camera_pv + ':Cross2X')
        self.marker2Y = caget(self.camera_pv + ':Cross2Y')
        self.marker3X = caget(self.camera_pv + ':Cross3X')
        self.marker3Y = caget(self.camera_pv + ':Cross3Y')
        self.marker4X = caget(self.camera_pv + ':Cross4X')
        self.marker4Y = caget(self.camera_pv + ':Cross4Y')
        return self.marker1X, self.marker1Y, self.marker2X, self.marker2Y
    def get_projections(self):
        self.x_projection = np.sum(self.active_image, axis=0)
        self.y_projection = np.sum(self.active_image, axis=1)
        self.x_projection -= self.x_projection.min()
        self.y_projection -= self.y_projection.min()
        return self.x_projection, self.y_projection
class transfocator_aligner(gigE_camera_accessor):
    def scan_transfocator(self, transfocator_motor,positions, image_sec):
        wid_x=[]
        wid_y=[]
        fig, ax=plt.subplots(2,1,sharex=True)
        fig.suptitle('Transfocator Optimization Plot')
        line1, = ax[0].plot([],[],'ro-') 
        line2, = ax[1].plot([],[],'ro-') 
        ax[0].set_ylabel('FWHM_x')
        ax[1].set_ylabel('FWHM_y')
        ax[1].set_xlabel('Transfocator Z-position')
        plt.ion()
        for idx,pos in enumerate(positions):
            transfocator_motor.umv(pos)
            #transfocator_motor.mv(pos, wait = True)
            timeout = time.time()+image_sec
            img_count=0
            collect=True
            while collect==True:
                img=self.get_image_roi()
                #if np.sum(img-np.min(img))<np.shape(img)[0]*np.shape(img)[1]:
                #    print('bad shot!')
                #    continue
                #print('shot okay!')
                if img_count==0:
                    images=img
                    img_count+=1
                else:
                    images+=img
                    img_count+=1
                if time.time()>timeout and img_count>=10:
                    collect=False
            images=images/img_count
            self.active_image=images-np.min(images)
            x,y=self.get_projections()
            opt_x=self.fit_scan(np.arange(0,len(x),1),x)
            opt_y=self.fit_scan(np.arange(0,len(y),1),y)
            wid_x.append(np.abs(opt_x[2]))
            wid_y.append(np.abs(opt_y[2]))
            if idx%5==0:
                line1.set_data(positions[:idx+1], wid_x)
                line2.set_data(positions[:idx+1], wid_y)
                ax[0].relim()  # Recalculate the data limits
                ax[1].relim()
                ax[0].autoscale_view()  
                ax[1].autoscale_view()
                fig.canvas.draw()  
                fig.canvas.flush_events()  
                plt.pause(0.1)  
        line1.set_data(positions,wid_x)
        line2.set_data(positions,wid_y)
        ax[0].relim()
        ax[1].relim()
        ax[0].autoscale_view()
        ax[1].autoscale_view()
        fig.canvas.draw()
        fig.canvas.flush_events()
        plt.show()
        plt.ioff()
        #plt.xlabel('Transfocator Z-Position')
    def fit_scan(self,x,y):
        maxi = np.percentile(y,95)
        mean_ind = np.argmin(y-maxi/2)
        guess = [maxi, x[mean_ind], np.std(x)]
        try:
            popt, pcov = curve_fit(gaussian, x, y,np.array(guess),maxfev=999999)
        except RuntimeError:
            guess_width_high=np.percentile(y,75)
            guess_width_low=np.percentile(y,25)
            print('bad fit')
            return [0,0,0,0]
        return popt 
def gaussian(x, amplitude, mean, stddev):
	return amplitude * np.exp(-((x - mean) / 4 / stddev)**2)

