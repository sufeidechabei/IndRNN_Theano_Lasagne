import theano
import theano.tensor as T

from lasagne import init
from lasagne import nonlinearities

from lasagne.layers import Layer
from lasagne.layers import DropoutLayer
class BatchNormLayer(Layer):
    def __init__(self, incoming, axes='auto', droprate=0.2, epsilon=1e-4, alpha=0.1,sparsity=1.0,
                 beta=init.Constant(0), gamma=init.Constant(1),
                 mean=init.Constant(0), inv_std=init.Constant(1), **kwargs):
        super(BatchNormLayer, self).__init__(incoming, **kwargs)

        if axes == 'auto':
            # default: normalize over all but the second axis
            axes = (0,) + tuple(range(2, len(self.input_shape)))
        elif isinstance(axes, int):
            axes = (axes,)
        self.axes = axes
        if len(axes)==1:
          self.mean_axes=self.axes
        else:
          self.mean_axes=(axes[1],)

        self.epsilon = epsilon
        self.alpha = alpha

        # create parameters, ignoring all dimensions in axes
        shape = [size for axis, size in enumerate(self.input_shape)
                 if axis not in self.axes]
        meanshape = [size for axis, size in enumerate(self.input_shape)
                 if axis not in self.mean_axes]
        if any(size is None for size in shape):
            raise ValueError("BatchNormLayer needs specified input sizes for "
                             "all axes not normalized over.")
        if beta is None:
            self.beta = None
        else:
            self.beta = self.add_param(beta, shape, 'beta',
                                       trainable=True, regularizable=False)
        if gamma is None:
            self.gamma = None
        else:
            self.gamma = self.add_param(gamma, shape, 'gamma',
                                        trainable=True, regularizable=True)
        self.mean = self.add_param(mean, meanshape, 'mean',
                                   trainable=False, regularizable=False)
        self.inv_std = self.add_param(inv_std, meanshape, 'inv_std',
                                      trainable=False, regularizable=False)
        #print('here',len(self.input_shape))
        self.sparsity=sparsity
        if len(self.input_shape)==3:
          self.dropout=DropoutLayer((self.input_shape[0],self.input_shape[1],self.input_shape[2]), p=droprate, shared_axes=(0,1), **kwargs)
        else:
          self.dropout=DropoutLayer((self.input_shape[0],self.input_shape[1]), p=droprate, shared_axes=(0,), **kwargs)

    def get_output_for(self, input, deterministic=False,
                       batch_norm_use_averages=None,
                       batch_norm_update_averages=None, **kwargs):
        if self.sparsity==1:
          input_mean = input.mean(self.mean_axes)
          input_inv_std = T.inv(T.sqrt(input.var(self.mean_axes) + self.epsilon))
        else:
          input_mean = input.mean(self.mean_axes)*(1.0/self.sparsity)
          input_inv_std = T.inv(T.sqrt(input.var(self.mean_axes) *(1.0/self.sparsity) -(1-self.sparsity)*T.sqr(input_mean) + self.epsilon))    

        # Decide whether to use the stored averages or mini-batch statistics
        if batch_norm_use_averages is None:
            batch_norm_use_averages = deterministic
        use_averages = batch_norm_use_averages

        if use_averages:
            mean = self.mean
            inv_std = self.inv_std
        else:
            mean = input_mean
            inv_std = input_inv_std

        # Decide whether to update the stored averages
        if batch_norm_update_averages is None:
            batch_norm_update_averages = not deterministic
        update_averages = batch_norm_update_averages

        if update_averages:
            # Trick: To update the stored statistics, we create memory-aliased
            # clones of the stored statistics:
            running_mean = theano.clone(self.mean, share_inputs=False)
            running_inv_std = theano.clone(self.inv_std, share_inputs=False)
            # set a default update for them:
            running_mean.default_update = ((1 - self.alpha) * running_mean +
                                           self.alpha * input_mean)
            running_inv_std.default_update = ((1 - self.alpha) *
                                              running_inv_std +
                                              self.alpha * input_inv_std)
            # and make sure they end up in the graph without participating in
            # the computation (this way their default_update will be collected
            # and applied, but the computation will be optimized away):
            mean += 0 * running_mean
            inv_std += 0 * running_inv_std

        # prepare dimshuffle pattern inserting broadcastable axes as needed
        param_axes = iter(range(input.ndim - len(self.axes)))
        pattern = ['x' if input_axis in self.axes
                   else next(param_axes)
                   for input_axis in range(input.ndim)]

        # apply dimshuffle pattern to all parameters
        beta = 0 if self.beta is None else self.beta.dimshuffle(pattern)
        gamma = 1 if self.gamma is None else self.gamma.dimshuffle(pattern)
        
        mean_param_axes = iter(range(input.ndim - len(self.mean_axes)))
        mean_pattern = ['x' if input_axis in self.mean_axes
                   else next(mean_param_axes)
                   for input_axis in range(input.ndim)]        
        mean = mean.dimshuffle(mean_pattern)
        inv_std = inv_std.dimshuffle(mean_pattern)
        
        input=self.dropout.get_output_for(input,deterministic=deterministic)

        # normalize
        normalized = (input - mean) * (gamma * inv_std) + beta
        return normalized

